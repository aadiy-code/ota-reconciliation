from enum import Enum
from datetime import date, datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import uuid


class BookingStatus(str, Enum):
    confirmed = "confirmed"
    modified = "modified"
    cancelled = "cancelled"
    no_show = "no_show"
    checked_in = "checked_in"
    checked_out = "checked_out"
    unknown = "unknown"


class PaymentType(str, Enum):
    pay_at_hotel = "pay_at_hotel"
    prepaid = "prepaid"
    virtual_card = "virtual_card"
    unknown = "unknown"


class SourcePlatform(str, Enum):
    booking_com = "booking_com"
    expedia = "expedia"
    pms = "pms"
    unknown = "unknown"


class ReconciliationStatus(str, Enum):
    matched = "matched"
    matched_with_minor_variance = "matched_with_minor_variance"
    missing_in_pms = "missing_in_pms"
    missing_in_ota = "missing_in_ota"
    duplicate_in_pms = "duplicate_in_pms"
    duplicate_in_ota = "duplicate_in_ota"
    cancellation_mismatch = "cancellation_mismatch"
    modification_mismatch = "modification_mismatch"
    source_mismatch = "source_mismatch"
    amount_mismatch = "amount_mismatch"
    pending_review = "pending_review"


class ReasonCode(str, Enum):
    no_pms_match = "no_pms_match"
    no_ota_match = "no_ota_match"
    duplicate_pms_records = "duplicate_pms_records"
    duplicate_ota_records = "duplicate_ota_records"
    status_conflict = "status_conflict"
    amount_difference = "amount_difference"
    room_type_difference = "room_type_difference"
    guest_name_difference = "guest_name_difference"
    date_difference = "date_difference"
    source_difference = "source_difference"
    incomplete_data = "incomplete_data"
    low_confidence_match = "low_confidence_match"


class CanonicalBooking(BaseModel):
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()))
    reconciliation_run_id: Optional[str] = None
    file_id: Optional[str] = None
    source_platform: SourcePlatform = SourcePlatform.unknown
    hotel_id: Optional[str] = None
    external_reservation_id: Optional[str] = None
    pms_reservation_id: Optional[str] = None
    channel_reference_id: Optional[str] = None
    booking_status: BookingStatus = BookingStatus.unknown
    guest_name_raw: Optional[str] = None
    guest_name_normalized: Optional[str] = None
    check_in_date: Optional[date] = None
    check_out_date: Optional[date] = None
    number_of_nights: Optional[int] = None
    booking_date: Optional[date] = None
    last_modified_at: Optional[datetime] = None
    room_type_raw: Optional[str] = None
    room_type_normalized: Optional[str] = None
    guest_count: Optional[int] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    currency: str = "INR"
    gross_amount: Optional[float] = None
    net_amount: Optional[float] = None
    taxes_and_fees: Optional[float] = None
    commission_amount: Optional[float] = None
    payment_type: PaymentType = PaymentType.unknown
    source_file_name: Optional[str] = None
    source_row_number: Optional[int] = None
    raw_payload_json: Optional[Dict[str, Any]] = None

    model_config = {"from_attributes": True}


# --- API Response Schemas ---

class FileUploadResponse(BaseModel):
    file_id: str
    file_name: str
    source_platform: str
    classifier_confidence: float
    row_count: Optional[int] = None
    parse_status: str


class ReconciliationRunCreate(BaseModel):
    file_ids: List[str]
    hotel_id: Optional[str] = None
    triggered_by: str = "user"


class ReconciliationRunResponse(BaseModel):
    id: str
    hotel_id: Optional[str]
    run_started_at: datetime
    run_completed_at: Optional[datetime]
    triggered_by: str
    status: str
    summary_json: Optional[Dict[str, Any]]
    created_at: datetime

    model_config = {"from_attributes": True}


class ReconciliationResultResponse(BaseModel):
    id: str
    reconciliation_run_id: str
    ota_booking_id: Optional[str]
    pms_booking_id: Optional[str]
    reconciliation_status: str
    confidence_score: float
    matched_rule: Optional[str]
    reason_codes_json: Optional[List[str]]
    explanation_text: Optional[str]
    created_at: datetime
    reviewed_by: Optional[str]
    reviewed_at: Optional[datetime]
    review_decision: Optional[str]
    review_notes: Optional[str]
    is_manual_override: bool

    # Embedded booking details for UI
    ota_booking: Optional[Dict[str, Any]] = None
    pms_booking: Optional[Dict[str, Any]] = None

    model_config = {"from_attributes": True}


class ReviewDecisionRequest(BaseModel):
    decision: str  # accepted, rejected, marked_variance
    notes: Optional[str] = None
    create_rule: bool = False
    actor: str = "user"


class MappingRuleCreate(BaseModel):
    hotel_id: Optional[str] = None
    rule_type: str
    source_platform: Optional[str] = None
    source_value: str
    target_value: str
    confidence: float = 1.0
    created_from: str = "user_feedback"


class MappingRuleResponse(BaseModel):
    id: str
    hotel_id: Optional[str]
    rule_type: str
    source_platform: Optional[str]
    source_value: str
    target_value: str
    confidence: float
    created_from: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExceptionFilters(BaseModel):
    status: Optional[str] = None
    source_platform: Optional[str] = None
    min_confidence: Optional[float] = None
    max_confidence: Optional[float] = None
    reason_code: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None


class AuditLogResponse(BaseModel):
    id: str
    reconciliation_run_id: Optional[str]
    result_id: Optional[str]
    action: str
    actor: str
    before_state_json: Optional[Dict[str, Any]]
    after_state_json: Optional[Dict[str, Any]]
    created_at: datetime

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
