from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from rapidfuzz import fuzz, process
from sqlalchemy.orm import Session

from ..models.db_models import SchemaTemplate
from ..schemas.canonical import SourcePlatform


FIELD_SYNONYMS: Dict[str, List[str]] = {
    "external_reservation_id": [
        "booking_number", "reservation_id", "confirmation_number",
        "itinerary_id", "booking_id", "reservation_number",
        "booking_reference", "confirmation_id", "booking_no",
        "res_id", "folio_number", "booking number",
    ],
    "guest_name_raw": [
        "guest_name", "booker_name", "customer_name", "traveler_name",
        "lead_guest", "primary_guest", "name", "guest", "customer",
        "passenger_name", "client_name",
    ],
    "check_in_date": [
        "check_in", "arrival_date", "check_in_date", "arrival",
        "check-in", "checkin_date", "check_in_dt", "from_date",
        "start_date", "arrival_dt",
    ],
    "check_out_date": [
        "check_out", "departure_date", "check_out_date", "departure",
        "check-out", "checkout_date", "check_out_dt", "to_date",
        "end_date", "departure_dt",
    ],
    "booking_status": [
        "status", "reservation_status", "booking_status", "state",
        "res_status", "current_status",
    ],
    "gross_amount": [
        "total_amount", "gross_amount", "total_price", "total_cost",
        "booking_value", "reservation_value", "total", "amount",
        "room_revenue", "gross_revenue", "total_revenue",
        "gross_booking_value_inr", "gross_booking_value",
        "total_amount_inr",
    ],
    "net_amount": [
        "net_amount", "net_rate", "hotel_collect", "net_revenue",
        "net_price", "net_booking_value",
    ],
    "commission_amount": [
        "commission", "commission_amount", "ota_commission",
        "agency_commission", "commission_value", "commission_inr",
    ],
    "room_type_raw": [
        "room_type", "room_category", "room_class", "accommodation_type",
        "room_name", "unit_type", "property_type",
    ],
    "guest_count": [
        "guests", "number_of_guests", "pax", "occupancy",
        "total_guests", "party_size",
    ],
    "adults": [
        "adults", "adult_count", "number_of_adults", "no_adults",
    ],
    "children": [
        "children", "child_count", "number_of_children", "no_children", "kids",
    ],
    "booking_date": [
        "booking_date", "created_date", "reservation_date",
        "date_booked", "book_date", "creation_date", "order_date",
    ],
    "currency": [
        "currency", "currency_code", "curr", "payment_currency",
        "property_currency",
    ],
    "payment_type": [
        "payment_type", "payment_method", "collection_method",
        "pay_type", "payment_model",
    ],
    "channel_reference_id": [
        "channel_reference", "ota_reference", "channel_id",
        "source_reference", "external_id", "partner_reference",
        "ota_reference_number",
    ],
    "pms_reservation_id": [
        "pms_id", "pms_reservation_id", "property_reservation_id",
        "internal_id", "hotel_confirmation_number", "hotel_conf_no",
    ],
    "taxes_and_fees": [
        "taxes", "tax_amount", "fees", "taxes_and_fees", "vat",
        "gst", "service_charge", "tax_fees",
    ],
    "hotel_id": [
        "hotel_id", "property_id", "hotel_code", "property_code",
    ],
    "source_platform": [
        "source_channel", "booking_source", "channel", "source",
        "ota_name", "platform",
    ],
}

REQUIRED_FIELDS = [
    "external_reservation_id",
    "guest_name_raw",
    "check_in_date",
    "check_out_date",
    "booking_status",
]


@dataclass
class MappingResult:
    column_mapping: Dict[str, str]  # source_col -> canonical_field
    confidence: float
    method: str
    missing_required_fields: List[str] = field(default_factory=list)
    unmapped_columns: List[str] = field(default_factory=list)


def _normalize_col(col: str) -> str:
    return col.lower().strip().replace(" ", "_").replace("-", "_").replace("(", "").replace(")", "")


class SchemaMapperService:
    def __init__(self):
        # Pre-build a flat synonym->canonical lookup
        self._synonym_to_canonical: Dict[str, str] = {}
        for canonical_field, synonyms in FIELD_SYNONYMS.items():
            for syn in synonyms:
                self._synonym_to_canonical[_normalize_col(syn)] = canonical_field

    def map_columns(
        self,
        headers: List[str],
        sample_rows: List[Dict],
        source_platform: str,
        hotel_id: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> MappingResult:
        # Tier 1: Try stored template
        if db is not None:
            template_result = self._try_template_match(headers, source_platform, db)
            if template_result is not None:
                return template_result

        # Tier 2: Rule-based
        return self._rule_based_mapping(headers, source_platform)

    def _try_template_match(
        self, headers: List[str], source_platform: str, db: Session
    ) -> Optional[MappingResult]:
        sig = sorted([_normalize_col(h) for h in headers])
        templates = db.query(SchemaTemplate).filter(
            SchemaTemplate.source_platform == source_platform
        ).all()
        for tmpl in templates:
            tmpl_sig = sorted([_normalize_col(s) for s in (tmpl.header_signature or [])])
            if sig == tmpl_sig and tmpl.confidence >= 0.95:
                mapping = tmpl.column_mapping_json or {}
                missing = [f for f in REQUIRED_FIELDS if f not in mapping.values()]
                unmapped = [h for h in headers if h not in mapping]
                return MappingResult(
                    column_mapping=mapping,
                    confidence=tmpl.confidence,
                    method="template_match",
                    missing_required_fields=missing,
                    unmapped_columns=unmapped,
                )
        return None

    def _rule_based_mapping(self, headers: List[str], source_platform: str) -> MappingResult:
        column_mapping: Dict[str, str] = {}
        used_canonical: set = set()
        scored_matches: List[tuple] = []  # (score, source_col, canonical_field)

        for header in headers:
            norm = _normalize_col(header)

            # Exact match in synonym lookup
            if norm in self._synonym_to_canonical:
                canonical = self._synonym_to_canonical[norm]
                scored_matches.append((100.0, header, canonical))
                continue

            # Fuzzy match against all synonyms
            best_score = 0.0
            best_canonical = None
            for syn_norm, canonical_field in self._synonym_to_canonical.items():
                score = fuzz.ratio(norm, syn_norm)
                if score > best_score:
                    best_score = score
                    best_canonical = canonical_field

            if best_score >= 75:
                scored_matches.append((best_score, header, best_canonical))

        # Sort by confidence descending, resolve conflicts (one canonical per source)
        scored_matches.sort(key=lambda x: -x[0])
        for score, source_col, canonical_field in scored_matches:
            if canonical_field not in used_canonical:
                column_mapping[source_col] = canonical_field
                used_canonical.add(canonical_field)

        # Calculate overall confidence
        if not headers:
            overall_confidence = 0.0
        else:
            mapped_count = len(column_mapping)
            overall_confidence = min(0.95, (mapped_count / len(headers)) * 0.95)
            # Boost if required fields are covered
            req_covered = sum(1 for f in REQUIRED_FIELDS if f in used_canonical)
            overall_confidence = min(0.95, overall_confidence + req_covered * 0.03)

        missing_required = [f for f in REQUIRED_FIELDS if f not in used_canonical]
        unmapped_cols = [h for h in headers if h not in column_mapping]

        return MappingResult(
            column_mapping=column_mapping,
            confidence=overall_confidence,
            method="rule_based",
            missing_required_fields=missing_required,
            unmapped_columns=unmapped_cols,
        )

    def save_template(
        self,
        headers: List[str],
        column_mapping: Dict[str, str],
        source_platform: str,
        db: Session,
        confidence: float = 1.0,
    ) -> None:
        sig = sorted([_normalize_col(h) for h in headers])
        existing = db.query(SchemaTemplate).filter(
            SchemaTemplate.source_platform == source_platform,
            SchemaTemplate.header_signature == sig,
        ).first()
        if existing:
            existing.usage_count += 1
            existing.column_mapping_json = column_mapping
        else:
            template = SchemaTemplate(
                source_platform=source_platform,
                template_name=f"{source_platform}_auto_{len(sig)}cols",
                header_signature=sig,
                column_mapping_json=column_mapping,
                confidence=confidence,
                usage_count=1,
            )
            db.add(template)
        db.commit()
