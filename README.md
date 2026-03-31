# OTA Reconciliation System

A production-ready Online Travel Agency (OTA) hotel reservation reconciliation system that matches bookings from Booking.com and Expedia against a Property Management System (PMS) to detect discrepancies, missing records, duplicates, and financial variances.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Streamlit Frontend (Port 8501)               │
│   Upload & Run | Dashboard | Exception Review | Results |       │
│   Mapping Rules | Audit Log                                     │
└────────────────────────┬────────────────────────────────────────┘
                         │ HTTP REST API
┌────────────────────────▼────────────────────────────────────────┐
│                   FastAPI Backend (Port 8000)                   │
│                                                                 │
│  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌──────────────────┐ │
│  │  Files  │  │  Recon   │  │ Review  │  │  Mapping Rules   │ │
│  │  API    │  │  API     │  │  API    │  │  API             │ │
│  └────┬────┘  └────┬─────┘  └────┬────┘  └────────┬─────────┘ │
│       │            │              │                 │           │
│  ┌────▼────────────▼──────────────▼─────────────────▼────────┐ │
│  │                    Service Layer                          │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐  │ │
│  │  │ File     │ │ Schema   │ │Normalizer│ │  Matcher   │  │ │
│  │  │Classifier│ │ Mapper   │ │          │ │            │  │ │
│  │  └──────────┘ └──────────┘ └──────────┘ └────────────┘  │ │
│  │  ┌──────────────────────────────────────────────────────┐│ │
│  │  │           Reconciliation Engine                      ││ │
│  │  └──────────────────────────────────────────────────────┘│ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐  │ │
│  │  │Exception │ │  Report  │ │  Audit   │ │  Feedback  │  │ │
│  │  │  Queue   │ │Generator │ │  Logger  │ │   Store    │  │ │
│  │  └──────────┘ └──────────┘ └──────────┘ └────────────┘  │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │              SQLite Database (SQLAlchemy ORM)              │ │
│  │  reconciliation_runs | files | raw_rows |                  │ │
│  │  normalized_bookings | reconciliation_results |            │ │
│  │  mapping_rules | audit_logs | schema_templates             │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Features

- **Multi-platform support**: Booking.com, Expedia, and PMS files
- **Automatic file classification**: Detects source platform from column headers
- **Intelligent schema mapping**: Maps varying column names to canonical fields using synonym dictionaries and fuzzy matching
- **Tiered matching algorithm**: Exact reference match → Exact structured match → Fuzzy match
- **Comprehensive reconciliation statuses**: Matched, Missing in PMS/OTA, Duplicates, Cancellation/Amount/Modification mismatches
- **Manual review queue**: Accept, reject, or mark variance on exceptions
- **Learning from feedback**: Creates mapping rules from manual review decisions
- **Excel/CSV export**: Multi-sheet Excel report with color coding
- **Audit trail**: Complete audit log of all actions
- **Streamlit dashboard**: Visual charts, exception review UI, and export buttons

## Requirements

- Python 3.11+
- pip

## Setup

```bash
# Clone / navigate to the project
cd ota-reconciliation

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env
# Edit .env if needed (defaults work for development)
```

## Running

### Start the Backend API

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at:
- API: http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Start the Frontend

In a new terminal:

```bash
streamlit run frontend/streamlit_app.py
```

The UI will be available at http://localhost:8501

## Running Tests

```bash
cd backend
pytest tests/ -v
```

## How to Use

### 1. Upload Files and Run Reconciliation

1. Go to the "Upload & Run" page
2. Upload Booking.com export file(s) (CSV or Excel)
3. Upload Expedia export file(s)
4. Upload PMS export file
5. Enter Hotel ID (optional)
6. Click "Start Reconciliation"
7. Wait for completion (typically a few seconds)

### 2. View Dashboard

- Select your reconciliation run from the dropdown
- View summary metrics: Match Rate, Total OTA/PMS bookings, Exceptions
- Browse the bar chart and pie chart breakdowns
- Download CSV or Excel reports

### 3. Review Exceptions

- Navigate to "Exception Review"
- Filter by status, confidence range, or reason code
- Expand each exception to see side-by-side OTA vs PMS comparison
- Read the auto-generated explanation
- Accept, Reject, or Mark as Variance
- Optionally create a mapping rule from the decision

### 4. Explore All Results

- Navigate to "Results Explorer"
- Filter by any status
- Search by guest name
- Export filtered results to CSV or Excel

### 5. Manage Mapping Rules

- View all existing mapping rules (room types, statuses, column mappings)
- Add new rules for custom hotel room type or status mappings
- Delete incorrect rules

### 6. Audit Log

- View complete history of all actions taken in the system
- Filter by run ID, actor, or action type

## Sample Files

Sample files are provided in `shared/sample_files/`:
- `booking_com_sample.csv` - 15 Booking.com reservations
- `expedia_sample.csv` - 15 Expedia reservations
- `pms_sample.csv` - 23 PMS records (includes OTA refs + direct bookings)

The sample data includes:
- 8 perfect Booking.com ↔ PMS matches
- 7 perfect Expedia ↔ PMS matches
- 2 OTA bookings missing in PMS
- 2 PMS bookings with OTA reference but no OTA file record
- 1 cancellation mismatch (BK1009: OTA=cancelled, PMS=confirmed)
- 1 amount mismatch (BK1010: PMS has different amount in duplicate record)
- 1 duplicate PMS record (PMS018 + PMS023 both reference BK1010)
- 3 direct PMS bookings (no OTA)

## Matching Logic

The system uses a three-tier matching strategy:

### Tier 1: Exact Reference Match (Confidence: 100)
- OTA `external_reservation_id` == PMS `channel_reference_id`
- Highest priority, most reliable

### Tier 2: Exact Structured Match (Confidence: 80-90)
- Check-in date match (exact)
- Check-out date match (exact)
- Guest name similarity >= 80% (using rapidfuzz token_sort_ratio)
- Amount within tolerance

### Tier 3: Fuzzy Match (Confidence: 40-85)
Weighted scoring across multiple fields:
- Guest name (35% weight) - using token_sort_ratio
- Check-in date (25% weight) - exact=100, within 1 day=80, else=0
- Check-out date (25% weight) - same
- Amount (15% weight) - within tolerance=100, else=40

## Confidence Score Explanation

| Range | Status | Action |
|-------|--------|--------|
| 100 | Exact reference match | Auto-accept |
| 85-99 | High confidence | Auto-accept, flag minor variances |
| 50-84 | Medium confidence | Manual review recommended |
| 0-49 | Low confidence | Manual review required |

## Amount Tolerance

Default tolerances (configurable in `.env`):
- Absolute: INR 200 (either direction)
- Percentage: 2% of booking value
- A match is accepted if either tolerance is satisfied

## Adding Custom Mapping Rules

### Via UI
1. Go to "Mapping Rules" page
2. Click "Add New Mapping Rule"
3. Enter rule type, source/target values, platform

### Via API
```bash
curl -X POST http://localhost:8000/api/v1/mapping-rules \
  -H "Content-Type: application/json" \
  -d '{
    "rule_type": "room_type",
    "source_platform": "booking_com",
    "source_value": "cozy studio apartment",
    "target_value": "studio",
    "confidence": 1.0,
    "created_from": "user_feedback"
  }'
```

### Supported Rule Types
- `room_type`: Map OTA room type names to standard categories
- `status`: Map platform-specific status strings to canonical status
- `guest_name`: Map known name variations
- `column_mapping`: Map column headers to canonical field names
- `amount_tolerance`: Custom amount tolerance per hotel

## File Format Documentation

### Booking.com Export Format
```
Booking Number, Property Name, Check-in, Check-out, Booker Name, Room Type,
Guests, Status, Gross Booking Value (INR), Commission (INR), Property Currency,
Booking Date, Payment Method
```

### Expedia Export Format
```
Itinerary ID, Hotel Confirmation Number, Check-In Date, Check-Out Date,
Guest Name, Room Type, Adults, Children, Total Amount (INR), Expedia Collect,
Hotel Collect, Status, Booking Date, Payment Model
```

### PMS Export Format
```
PMS Reservation ID, OTA Reference Number, Source Channel, Guest Name,
Check In Date, Check Out Date, Room Type, Adults, Children, Total Revenue (INR),
Net Revenue (INR), Tax Amount (INR), Status, Booking Date, Payment Type
```

## Configuration Reference

All settings can be overridden in `.env`:

| Setting | Default | Description |
|---------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./ota_reconciliation.db` | Database connection URL |
| `UPLOAD_DIR` | `./uploads` | Directory for uploaded files |
| `NAME_AUTO_MATCH_THRESHOLD` | `0.92` | Name similarity for auto-match (0-1) |
| `NAME_MANUAL_REVIEW_THRESHOLD` | `0.80` | Name similarity for manual review (0-1) |
| `AMOUNT_TOLERANCE_ABSOLUTE` | `200.0` | Absolute INR tolerance for amounts |
| `AMOUNT_TOLERANCE_PERCENT` | `0.02` | Percentage tolerance for amounts |
| `DATE_TOLERANCE_DAYS` | `1` | Days tolerance for date matching |
| `HIGH_CONFIDENCE_THRESHOLD` | `85.0` | Confidence score for auto-accept |
| `MANUAL_REVIEW_THRESHOLD` | `50.0` | Below this confidence = always review |
| `AI_SCHEMA_MAPPING_ENABLED` | `false` | Enable AI-assisted schema mapping |
| `ANTHROPIC_API_KEY` | `` | API key for AI schema mapping |

## API Reference

### Files
- `POST /api/v1/files/upload` - Upload file(s)
- `GET /api/v1/files/{file_id}` - Get file metadata

### Reconciliation
- `POST /api/v1/reconciliation/start` - Start reconciliation run
- `GET /api/v1/reconciliation/runs` - List all runs
- `GET /api/v1/reconciliation/runs/{run_id}` - Get run details
- `GET /api/v1/reconciliation/runs/{run_id}/summary` - Get summary stats
- `GET /api/v1/reconciliation/runs/{run_id}/results` - Get all results
- `GET /api/v1/reconciliation/runs/{run_id}/exceptions` - Get exceptions
- `GET /api/v1/reconciliation/runs/{run_id}/export?format=csv|xlsx` - Export

### Review
- `GET /api/v1/review/{run_id}/queue` - Get pending review items
- `POST /api/v1/review/{result_id}` - Submit review decision

### Mapping Rules
- `GET /api/v1/mapping-rules` - List rules
- `POST /api/v1/mapping-rules` - Create rule
- `DELETE /api/v1/mapping-rules/{rule_id}` - Delete rule

### Audit
- `GET /api/v1/audit-logs` - Get audit log

### Health
- `GET /api/v1/health` - Health check
