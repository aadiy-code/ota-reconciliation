import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, DateTime, Float, Integer, Boolean, Date,
    ForeignKey, JSON, Text
)
from sqlalchemy.orm import relationship
from ..database import Base


def gen_uuid():
    return str(uuid.uuid4())


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    hotel_id = Column(String(100), nullable=True)
    run_started_at = Column(DateTime, default=datetime.utcnow)
    run_completed_at = Column(DateTime, nullable=True)
    triggered_by = Column(String(100), default="user")
    status = Column(String(50), default="pending")  # pending, running, completed, failed
    summary_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    files = relationship("File", back_populates="run", cascade="all, delete-orphan")
    results = relationship("ReconciliationResult", back_populates="run", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="run", cascade="all, delete-orphan")


class File(Base):
    __tablename__ = "files"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    reconciliation_run_id = Column(String(36), ForeignKey("reconciliation_runs.id"), nullable=True)
    file_name = Column(String(500))
    source_platform = Column(String(50), default="unknown")  # booking_com, expedia, pms, unknown
    file_type = Column(String(10))  # csv, xlsx, xls
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    parse_status = Column(String(20), default="pending")  # pending, success, failed
    row_count = Column(Integer, nullable=True)
    file_path = Column(String(1000))
    schema_version = Column(String(50), nullable=True)
    classifier_confidence = Column(Float, nullable=True)

    run = relationship("ReconciliationRun", back_populates="files")
    raw_rows = relationship("RawRow", back_populates="file", cascade="all, delete-orphan")
    normalized_bookings = relationship("NormalizedBooking", back_populates="file", cascade="all, delete-orphan")


class RawRow(Base):
    __tablename__ = "raw_rows"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    file_id = Column(String(36), ForeignKey("files.id"))
    source_row_number = Column(Integer)
    raw_payload_json = Column(JSON)

    file = relationship("File", back_populates="raw_rows")


class NormalizedBooking(Base):
    __tablename__ = "normalized_bookings"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    reconciliation_run_id = Column(String(36), ForeignKey("reconciliation_runs.id"), nullable=True)
    file_id = Column(String(36), ForeignKey("files.id"), nullable=True)
    source_platform = Column(String(50))
    hotel_id = Column(String(100), nullable=True)
    external_reservation_id = Column(String(200), nullable=True)
    pms_reservation_id = Column(String(200), nullable=True)
    channel_reference_id = Column(String(200), nullable=True)
    booking_status = Column(String(50), default="unknown")
    guest_name_raw = Column(String(500))
    guest_name_normalized = Column(String(500))
    check_in_date = Column(Date, nullable=True)
    check_out_date = Column(Date, nullable=True)
    number_of_nights = Column(Integer, nullable=True)
    booking_date = Column(Date, nullable=True)
    last_modified_at = Column(DateTime, nullable=True)
    room_type_raw = Column(String(200), nullable=True)
    room_type_normalized = Column(String(200), nullable=True)
    guest_count = Column(Integer, nullable=True)
    adults = Column(Integer, nullable=True)
    children = Column(Integer, nullable=True)
    currency = Column(String(10), default="INR")
    gross_amount = Column(Float, nullable=True)
    net_amount = Column(Float, nullable=True)
    taxes_and_fees = Column(Float, nullable=True)
    commission_amount = Column(Float, nullable=True)
    payment_type = Column(String(50), default="unknown")
    source_file_name = Column(String(500))
    source_row_number = Column(Integer)
    raw_payload_json = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

    file = relationship("File", back_populates="normalized_bookings")
    ota_results = relationship(
        "ReconciliationResult",
        foreign_keys="ReconciliationResult.ota_booking_id",
        back_populates="ota_booking"
    )
    pms_results = relationship(
        "ReconciliationResult",
        foreign_keys="ReconciliationResult.pms_booking_id",
        back_populates="pms_booking"
    )


class ReconciliationResult(Base):
    __tablename__ = "reconciliation_results"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    reconciliation_run_id = Column(String(36), ForeignKey("reconciliation_runs.id"))
    ota_booking_id = Column(String(36), ForeignKey("normalized_bookings.id"), nullable=True)
    pms_booking_id = Column(String(36), ForeignKey("normalized_bookings.id"), nullable=True)
    reconciliation_status = Column(String(100))
    confidence_score = Column(Float, default=0.0)
    matched_rule = Column(String(100), nullable=True)
    reason_codes_json = Column(JSON, default=list)
    explanation_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_by = Column(String(200), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_decision = Column(String(50), nullable=True)  # accepted, rejected, marked_variance
    review_notes = Column(Text, nullable=True)
    is_manual_override = Column(Boolean, default=False)

    run = relationship("ReconciliationRun", back_populates="results")
    ota_booking = relationship("NormalizedBooking", foreign_keys=[ota_booking_id], back_populates="ota_results")
    pms_booking = relationship("NormalizedBooking", foreign_keys=[pms_booking_id], back_populates="pms_results")


class MappingRule(Base):
    __tablename__ = "mapping_rules"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    hotel_id = Column(String(100), nullable=True)
    rule_type = Column(String(50))  # column_mapping, room_type, status, guest_name, amount_tolerance
    source_platform = Column(String(50), nullable=True)
    source_value = Column(String(500))
    target_value = Column(String(500))
    confidence = Column(Float, default=1.0)
    created_from = Column(String(50))  # seed, user_feedback, ai_suggestion
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    reconciliation_run_id = Column(String(36), ForeignKey("reconciliation_runs.id"), nullable=True)
    result_id = Column(String(36), nullable=True)
    action = Column(String(200))
    actor = Column(String(200))
    before_state_json = Column(JSON, nullable=True)
    after_state_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    run = relationship("ReconciliationRun", back_populates="audit_logs")


class SchemaTemplate(Base):
    __tablename__ = "schema_templates"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    source_platform = Column(String(50))
    template_name = Column(String(200))
    header_signature = Column(JSON)  # sorted list of column names
    column_mapping_json = Column(JSON)
    confidence = Column(Float, default=1.0)
    usage_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
