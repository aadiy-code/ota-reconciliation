# OTA Reconciliation System - Architecture Documentation

## Module Overview and Interactions

```
Frontend (Streamlit)
    │
    │  HTTP REST
    ▼
FastAPI Application (main.py)
    │
    ├── /api/routes/files.py          → FileClassifierService, SchemaMapperService
    ├── /api/routes/reconciliation.py → ReconciliationService, NormalizerService
    ├── /api/routes/review.py         → ExceptionQueueService, AuditLoggerService
    ├── /api/routes/mapping_rules.py  → FeedbackStoreService
    └── /api/routes/health.py

Services Layer:
    FileClassifierService   →  Detects OTA platform from file headers
    SchemaMapperService     →  Maps arbitrary columns to canonical fields
    BookingNormalizerService→  Normalizes dates, amounts, names, statuses
    MatchingService         →  Core matching algorithm (tiered)
    ReconciliationService   →  Orchestrates full reconciliation workflow
    ExceptionQueueService   →  Manages manual review queue
    ReportGeneratorService  →  CSV and Excel export
    AuditLoggerService      →  Persists audit trail
    FeedbackStoreService    →  CRUD for mapping rules, seeding

Data Flow:
    Upload CSV/Excel
         │
    FileClassifier → detects platform (booking_com / expedia / pms)
         │
    SchemaMapper → maps headers to canonical fields
         │
    Normalizer → normalize each row (dates, amounts, names, statuses)
         │
    Store as NormalizedBooking in DB
         │
    MatchingService → match OTA bookings against PMS bookings
         │
    ReconciliationEngine → assign statuses, detect duplicates, generate explanations
         │
    Store ReconciliationResult in DB
         │
    ExceptionQueue → surface exceptions for manual review
         │
    ReportGenerator → export results
```

## Matching Algorithm - Pseudocode

```python
def match_all(ota_bookings, pms_bookings):
    used_pms_ids = set()
    results = []

    for ota in ota_bookings:
        available_pms = [p for p in pms_bookings if p.id not in used_pms_ids]

        # Priority 1: Exact Reference Match
        match = find_exact_ref(ota.external_reservation_id, available_pms)
        if match:
            results.append(MatchResult(ota, match, confidence=100))
            used_pms_ids.add(match.id)
            continue

        # Priority 2: Exact Structured Match
        match = find_exact_structured(ota, available_pms)
        if match:
            results.append(MatchResult(ota, match, confidence=80-90))
            used_pms_ids.add(match.id)
            continue

        # Priority 3: Fuzzy Match
        candidates = find_fuzzy(ota, available_pms)
        if candidates:
            best = candidates[0]  # highest scoring
            results.append(MatchResult(ota, best, confidence=best.score))
            used_pms_ids.add(best.pms.id)
        else:
            results.append(MatchResult(ota, None, status=MISSING_IN_PMS))

    return results


def find_exact_ref(ota_ref, pms_list):
    for pms in pms_list:
        if pms.channel_reference_id == ota_ref:
            return pms
    return None


def find_exact_structured(ota, pms_list):
    """Match on dates (exact) + name (>= 80%) + amount (within tolerance)."""
    best = None
    best_confidence = 0

    for pms in pms_list:
        if not dates_match(ota.check_in, pms.check_in, tolerance=0):
            continue
        if not dates_match(ota.check_out, pms.check_out, tolerance=0):
            continue

        name_score = token_sort_ratio(ota.guest_name_normalized, pms.guest_name_normalized)
        if name_score < NAME_REVIEW_THRESHOLD:
            continue

        amount_ok = amounts_within_tolerance(ota.gross_amount, pms.gross_amount)
        confidence = 90 - (0 if amount_ok else 10) - (0 if name_score >= NAME_AUTO else 5)

        if confidence > best_confidence:
            best_confidence = confidence
            best = (pms, confidence)

    return best


def find_fuzzy(ota, pms_list):
    """Score each PMS booking across multiple dimensions."""
    scored = []

    for pms in pms_list:
        name_score = token_sort_ratio(ota.guest_name_normalized, pms.guest_name_normalized)
        ci_score = 100 if exact_date(ota.ci, pms.ci) else (80 if within_day(ota.ci, pms.ci) else 0)
        co_score = 100 if exact_date(ota.co, pms.co) else (80 if within_day(ota.co, pms.co) else 0)
        amount_score = 100 if amounts_ok(ota.amount, pms.amount) else 40

        weighted_confidence = (
            name_score * 0.35 +
            ci_score * 0.25 +
            co_score * 0.25 +
            amount_score * 0.15
        )

        if weighted_confidence >= 40:
            scored.append((pms, weighted_confidence))

    return sorted(scored, key=lambda x: -x[1])[:5]
```

## Confidence Scoring Formula

For fuzzy matches:
```
confidence = name_score * 0.35
           + check_in_score * 0.25
           + check_out_score * 0.25
           + amount_score * 0.15

Where:
  name_score = rapidfuzz.token_sort_ratio(name1, name2)   # 0-100
  date_score = 100 (exact) | 80 (within 1 day) | 0 (different)
  amount_score = 100 (within tolerance) | 40 (different)

Penalties applied:
  - status_conflict: -5
  - name_below_review_threshold: -10

Final confidence capped at 85 for fuzzy matches.
```

For structured matches:
```
confidence = 90
           - (10 if amount_out_of_tolerance)
           - (5 if name_below_auto_threshold)
```

For exact reference matches:
```
confidence = 100 (always)
```

## Reconciliation Status Assignment

```
MatchResult → ReconciliationStatus:

  if confidence == 100 and no reason_codes:
    → matched

  if reason_codes contains status_conflict:
    if ota_cancelled XOR pms_cancelled:
      → cancellation_mismatch
    elif room_type_different:
      → modification_mismatch

  if reason_codes contains amount_difference:
    → amount_mismatch

  if reason_codes ⊆ {room_type_difference, guest_name_difference, low_confidence}:
    if confidence >= HIGH_THRESHOLD:
      → matched_with_minor_variance
    else:
      → pending_review

  if no match found:
    → missing_in_pms

  PMS booking with OTA reference, unmatched:
    → missing_in_ota

  Duplicate OTA records (same reservation_id):
    → duplicate_in_ota

  Duplicate PMS records (same channel_reference_id):
    → duplicate_in_pms
```

## How to Extend with New OTA Platforms

1. Add platform to `SourcePlatform` enum in `canonical.py`

2. Add known headers to `FileClassifierService` in `file_classifier.py`:
```python
NEW_OTA_HEADERS = {
    "booking_ref", "guest_full_name", "arrival", "departure", ...
}
NEW_OTA_STRONG_SIGNALS = {
    "unique_header_that_only_new_ota_has",
}
```

3. Add column synonyms to `FIELD_SYNONYMS` in `schema_mapper.py` if the platform uses non-standard column names.

4. Add status mapping to `normalizer.py`:
```python
NEW_OTA_STATUS_MAP = {
    "active": "confirmed",
    "void": "cancelled",
    ...
}
```

5. Update `normalize_status()` to handle the new platform key.

6. Add sample CSV to `shared/sample_files/`.

7. Update `seed_config/room_type_mapping.json` with platform-specific room type mappings.

## AI Integration Points

AI-assisted schema mapping can be enabled via:
```
AI_SCHEMA_MAPPING_ENABLED=true
ANTHROPIC_API_KEY=your-key
```

When enabled, if the rule-based schema mapper confidence is below a threshold (~60%), the system can call Claude to:
1. Inspect sample rows
2. Suggest column-to-canonical mappings
3. Return a mapping JSON with confidence scores

This is implemented as Tier 3 in `SchemaMapperService.map_columns()`. The AI call happens only when:
- Rule-based confidence < 0.60
- `AI_SCHEMA_MAPPING_ENABLED` is True
- `ANTHROPIC_API_KEY` is set

## Database Schema Rationale

### Why SQLite for MVP?
- Zero configuration, file-based
- Sufficient for single-hotel, single-server deployment
- Easily upgradeable to PostgreSQL by changing `DATABASE_URL`
- SQLAlchemy ORM abstracts the difference

### Why separate `raw_rows` and `normalized_bookings`?
- Preserves original data for audit/debugging
- Normalized bookings can be re-generated if mapping rules change
- Enables reprocessing without re-uploading files

### Why UUID primary keys?
- Globally unique without coordination
- Safe for eventual distribution
- No auto-increment conflicts when merging data

### Why JSON columns for `reason_codes`, `summary_json`?
- Flexible schema for evolving requirements
- No need to add new columns for new reason codes
- SQLite supports JSON operations natively

## How Feedback Learning Works

1. User reviews an exception and clicks "Accept" or "Mark Variance"
2. If `create_rule=True`, `ExceptionQueueService.create_mapping_rule_from_decision()` is called
3. It compares OTA and PMS booking fields:
   - If guest names differ: creates a `guest_name` rule (OTA name → PMS name)
   - If room types differ: creates a `room_type` rule (OTA room → normalized room)
4. Rules are stored in `mapping_rules` table with `created_from="user_feedback"`
5. On next reconciliation run, `BookingNormalizerService` loads these rules and applies them
6. This improves match rates over time without code changes

## Extending Amount Tolerance Per Hotel

Add a rule:
```json
{
  "rule_type": "amount_tolerance",
  "hotel_id": "HOTEL001",
  "source_value": "absolute",
  "target_value": "500"
}
```

The reconciliation engine can be extended to load hotel-specific tolerances from `mapping_rules` before matching.
