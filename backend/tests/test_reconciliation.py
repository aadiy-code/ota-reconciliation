import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.schemas.canonical import (
    CanonicalBooking, BookingStatus, ReconciliationStatus, SourcePlatform, PaymentType
)
from app.services.reconciliation_engine import ReconciliationService
from app.services.exception_queue import ExceptionQueueService
from app.models.db_models import (
    ReconciliationRun, NormalizedBooking, ReconciliationResult
)
from app.schemas.canonical import ReviewDecisionRequest

from .conftest import make_ota_booking, make_pms_booking
from datetime import datetime


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)


@pytest.fixture
def db(engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    yield session
    session.close()


def _create_run(db, run_id="test-run-001"):
    run = ReconciliationRun(
        id=run_id,
        triggered_by="test",
        status="running",
        run_started_at=datetime.utcnow(),
    )
    db.add(run)
    db.commit()
    return run


def _persist_bookings(db, bookings, run_id):
    """Save CanonicalBooking objects to DB as NormalizedBooking."""
    for b in bookings:
        nb = NormalizedBooking(
            id=b.id,
            reconciliation_run_id=run_id,
            source_platform=b.source_platform.value,
            external_reservation_id=b.external_reservation_id,
            pms_reservation_id=b.pms_reservation_id,
            channel_reference_id=b.channel_reference_id,
            guest_name_raw=b.guest_name_raw or "",
            guest_name_normalized=b.guest_name_normalized or "",
            booking_status=b.booking_status.value,
            check_in_date=b.check_in_date,
            check_out_date=b.check_out_date,
            number_of_nights=b.number_of_nights,
            room_type_raw=b.room_type_raw,
            room_type_normalized=b.room_type_normalized,
            gross_amount=b.gross_amount,
            net_amount=b.net_amount,
            currency=b.currency,
            payment_type=b.payment_type.value,
            source_file_name=b.source_file_name or "",
            source_row_number=b.source_row_number or 0,
            raw_payload_json={},
        )
        db.add(nb)
    db.commit()


def test_full_reconciliation_run(db):
    """Run complete reconciliation with mixed scenarios."""
    svc = ReconciliationService()
    run_id = "test-full-run"
    _create_run(db, run_id)

    ota_bookings = [
        make_ota_booking(reservation_id="BK001", guest_name_normalized="rajesh kumar",
                         check_in=date(2026, 4, 1), check_out=date(2026, 4, 4), gross_amount=18000.0),
        make_ota_booking(reservation_id="BK002", guest_name_normalized="priya sharma",
                         check_in=date(2026, 4, 5), check_out=date(2026, 4, 8), gross_amount=12000.0),
        make_ota_booking(reservation_id="BK003", guest_name_normalized="no match user",
                         check_in=date(2026, 7, 1), check_out=date(2026, 7, 4), gross_amount=50000.0),
    ]

    pms_bookings = [
        make_pms_booking(pms_id="P001", channel_reference="BK001",
                         guest_name_normalized="rajesh kumar",
                         check_in=date(2026, 4, 1), check_out=date(2026, 4, 4), gross_amount=18000.0),
        make_pms_booking(pms_id="P002", channel_reference="BK002",
                         guest_name_normalized="priya sharma",
                         check_in=date(2026, 4, 5), check_out=date(2026, 4, 8), gross_amount=12000.0),
        make_pms_booking(pms_id="P003", channel_reference="BK_ORPHAN",
                         guest_name_normalized="orphan pms user",
                         check_in=date(2026, 5, 1), check_out=date(2026, 5, 3), gross_amount=9000.0),
    ]

    _persist_bookings(db, ota_bookings + pms_bookings, run_id)

    summary = svc.run_reconciliation(run_id, ota_bookings, pms_bookings, db)

    # Assertions
    assert summary.total_ota_bookings >= 2
    assert summary.matched >= 2 or summary.matched + summary.matched_with_minor_variance >= 2
    assert summary.missing_in_pms >= 1  # BK003 has no PMS match

    # Check DB has results
    results = db.query(ReconciliationResult).filter(
        ReconciliationResult.reconciliation_run_id == run_id
    ).all()
    assert len(results) > 0


def test_manual_override(db):
    """Apply manual review decision and verify state changes."""
    svc = ReconciliationService()
    exception_svc = ExceptionQueueService()
    run_id = "test-override-run"
    _create_run(db, run_id)

    ota = make_ota_booking(reservation_id="BK_OVERRIDE")
    pms = make_pms_booking(channel_reference="BK_OVERRIDE", gross_amount=25000.0)  # Different amount
    ota_with_diff = make_ota_booking(reservation_id="BK_OVERRIDE", gross_amount=22000.0)

    _persist_bookings(db, [ota_with_diff, pms], run_id)

    # Run reconciliation
    summary = svc.run_reconciliation(run_id, [ota_with_diff], [pms], db)

    # Get results
    results = db.query(ReconciliationResult).filter(
        ReconciliationResult.reconciliation_run_id == run_id
    ).all()
    assert len(results) > 0

    result = results[0]
    original_status = result.reconciliation_status
    result_id = result.id

    # Apply review decision
    decision = ReviewDecisionRequest(
        decision="accepted",
        notes="Verified manually - hotel price difference approved",
        create_rule=False,
        actor="test_reviewer",
    )

    updated = exception_svc.apply_review_decision(result_id, decision, db)

    assert updated.review_decision == "accepted"
    assert updated.reviewed_by == "test_reviewer"
    assert updated.reviewed_at is not None
    assert updated.is_manual_override is True
    assert updated.reconciliation_status == "matched"


def test_rerun_consistency(db):
    """Running same data twice should produce the same number of results."""
    svc = ReconciliationService()

    ota_bookings = [
        make_ota_booking(reservation_id="CONS_BK001", guest_name_normalized="test user one",
                         check_in=date(2026, 4, 1), check_out=date(2026, 4, 3), gross_amount=10000.0),
        make_ota_booking(reservation_id="CONS_BK002", guest_name_normalized="test user two",
                         check_in=date(2026, 4, 5), check_out=date(2026, 4, 7), gross_amount=15000.0),
    ]

    pms_bookings = [
        make_pms_booking(pms_id="CONS_P001", channel_reference="CONS_BK001",
                         guest_name_normalized="test user one",
                         check_in=date(2026, 4, 1), check_out=date(2026, 4, 3), gross_amount=10000.0),
        make_pms_booking(pms_id="CONS_P002", channel_reference="CONS_BK002",
                         guest_name_normalized="test user two",
                         check_in=date(2026, 4, 5), check_out=date(2026, 4, 7), gross_amount=15000.0),
    ]

    # Run 1
    run_id_1 = "consistency-run-1"
    _create_run(db, run_id_1)
    _persist_bookings(db, ota_bookings + pms_bookings, run_id_1)
    summary1 = svc.run_reconciliation(run_id_1, ota_bookings, pms_bookings, db)

    # Create new booking objects with new UUIDs for run 2
    ota_bookings_2 = [
        make_ota_booking(reservation_id="CONS_BK001", guest_name_normalized="test user one",
                         check_in=date(2026, 4, 1), check_out=date(2026, 4, 3), gross_amount=10000.0),
        make_ota_booking(reservation_id="CONS_BK002", guest_name_normalized="test user two",
                         check_in=date(2026, 4, 5), check_out=date(2026, 4, 7), gross_amount=15000.0),
    ]
    pms_bookings_2 = [
        make_pms_booking(pms_id="CONS_P003", channel_reference="CONS_BK001",
                         guest_name_normalized="test user one",
                         check_in=date(2026, 4, 1), check_out=date(2026, 4, 3), gross_amount=10000.0),
        make_pms_booking(pms_id="CONS_P004", channel_reference="CONS_BK002",
                         guest_name_normalized="test user two",
                         check_in=date(2026, 4, 5), check_out=date(2026, 4, 7), gross_amount=15000.0),
    ]

    # Run 2
    run_id_2 = "consistency-run-2"
    _create_run(db, run_id_2)
    _persist_bookings(db, ota_bookings_2 + pms_bookings_2, run_id_2)
    summary2 = svc.run_reconciliation(run_id_2, ota_bookings_2, pms_bookings_2, db)

    # Both runs should produce same outcomes
    assert summary1.matched + summary1.matched_with_minor_variance == summary2.matched + summary2.matched_with_minor_variance
    assert summary1.missing_in_pms == summary2.missing_in_pms
    assert summary1.match_rate_percent == summary2.match_rate_percent
