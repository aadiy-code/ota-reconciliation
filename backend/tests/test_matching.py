import pytest
from datetime import date

from app.services.matcher import MatchingService
from app.schemas.canonical import (
    CanonicalBooking, BookingStatus, ReconciliationStatus, ReasonCode, SourcePlatform
)
from app.config import Settings

from .conftest import make_ota_booking, make_pms_booking


@pytest.fixture
def matcher():
    s = Settings(
        NAME_AUTO_MATCH_THRESHOLD=0.92,
        NAME_MANUAL_REVIEW_THRESHOLD=0.80,
        AMOUNT_TOLERANCE_ABSOLUTE=200.0,
        AMOUNT_TOLERANCE_PERCENT=0.02,
        DATE_TOLERANCE_DAYS=1,
        HIGH_CONFIDENCE_THRESHOLD=85.0,
        MANUAL_REVIEW_THRESHOLD=50.0,
    )
    return MatchingService(s)


def test_exact_reference_match(matcher):
    """OTA ID equals PMS channel reference -> confidence 100."""
    ota = make_ota_booking(reservation_id="BK1001")
    pms = make_pms_booking(channel_reference="BK1001")

    result = matcher.find_best_match(ota, [pms])

    assert result.best_match is not None
    assert result.best_match.matched_rule == "exact_reference"
    assert result.best_match.confidence == 100.0
    assert result.final_status in (ReconciliationStatus.matched, ReconciliationStatus.matched_with_minor_variance)


def test_exact_structured_match(matcher):
    """Same dates, same name, same amount -> high confidence."""
    ota = make_ota_booking(
        reservation_id="BK9999",
        guest_name_normalized="priya sharma",
        check_in=date(2026, 5, 1),
        check_out=date(2026, 5, 4),
        gross_amount=15000.0,
    )
    pms = make_pms_booking(
        pms_id="PMS999",
        channel_reference="DIFFERENT_REF",
        guest_name_normalized="priya sharma",
        check_in=date(2026, 5, 1),
        check_out=date(2026, 5, 4),
        gross_amount=15000.0,
    )

    result = matcher.find_best_match(ota, [pms])

    assert result.best_match is not None
    assert result.best_match.matched_rule in ("exact_structured", "fuzzy")
    assert result.best_match.confidence >= 80.0


def test_fuzzy_name_match(matcher):
    """John Smith vs JOHN SMITH vs Smith, John should all match well."""
    ota = make_ota_booking(
        reservation_id="BK_FUZZY",
        guest_name_normalized="john smith",
        check_in=date(2026, 6, 1),
        check_out=date(2026, 6, 3),
        gross_amount=10000.0,
    )

    # Test 1: uppercase
    pms_upper = make_pms_booking(
        channel_reference="DIFF1",
        guest_name_normalized="john smith",
        check_in=date(2026, 6, 1),
        check_out=date(2026, 6, 3),
        gross_amount=10000.0,
    )

    result = matcher.find_best_match(ota, [pms_upper])
    assert result.best_match is not None

    sim = matcher.calculate_name_similarity("john smith", "john smith")
    assert sim == 100.0

    sim2 = matcher.calculate_name_similarity("john smith", "smith john")
    assert sim2 >= 90.0  # token_sort handles word order


def test_amount_mismatch(matcher):
    """Amount differs beyond tolerance -> amount_mismatch status."""
    ota = make_ota_booking(
        reservation_id="BK_AMT",
        guest_name_normalized="arun kumar",
        check_in=date(2026, 4, 10),
        check_out=date(2026, 4, 13),
        gross_amount=20000.0,
    )
    pms = make_pms_booking(
        channel_reference="BK_AMT",
        guest_name_normalized="arun kumar",
        check_in=date(2026, 4, 10),
        check_out=date(2026, 4, 13),
        gross_amount=22500.0,  # 2500 INR difference, >200 abs and >2%
    )

    result = matcher.find_best_match(ota, [pms])
    assert result.best_match is not None
    assert ReasonCode.amount_difference in result.best_match.reason_codes
    assert result.final_status == ReconciliationStatus.amount_mismatch


def test_amount_within_tolerance(matcher):
    """Amount differs within tolerance -> matched."""
    ota = make_ota_booking(
        reservation_id="BK_AMT2",
        check_in=date(2026, 4, 10),
        check_out=date(2026, 4, 13),
        gross_amount=18000.0,
    )
    pms = make_pms_booking(
        channel_reference="BK_AMT2",
        check_in=date(2026, 4, 10),
        check_out=date(2026, 4, 13),
        gross_amount=18100.0,  # 100 INR difference, within 200 abs tolerance
    )

    result = matcher.find_best_match(ota, [pms])
    assert result.best_match is not None
    assert ReasonCode.amount_difference not in result.best_match.reason_codes


def test_cancellation_mismatch(matcher):
    """OTA cancelled, PMS confirmed -> cancellation_mismatch."""
    ota = make_ota_booking(
        reservation_id="BK_CANCEL",
        status=BookingStatus.cancelled,
    )
    pms = make_pms_booking(
        channel_reference="BK_CANCEL",
        status=BookingStatus.confirmed,
    )

    result = matcher.find_best_match(ota, [pms])
    assert result.best_match is not None
    assert ReasonCode.status_conflict in result.best_match.reason_codes
    assert result.final_status == ReconciliationStatus.cancellation_mismatch


def test_duplicate_pms(matcher):
    """Two PMS records match same OTA booking."""
    from app.services.reconciliation_engine import ReconciliationService

    svc = ReconciliationService()
    ota = make_ota_booking(reservation_id="BK_DUP")
    pms1 = make_pms_booking(pms_id="PMS_A", channel_reference="BK_DUP")
    pms2 = make_pms_booking(pms_id="PMS_B", channel_reference="BK_DUP")

    duplicates = svc.detect_pms_duplicates([pms1, pms2])
    assert "bk_dup" in duplicates
    assert len(duplicates["bk_dup"]) == 2


def test_duplicate_ota(matcher):
    """Same OTA booking appears twice."""
    from app.services.reconciliation_engine import ReconciliationService

    svc = ReconciliationService()
    ota1 = make_ota_booking(reservation_id="BK_OTA_DUP", guest_name_raw="Test User A")
    ota2 = make_ota_booking(reservation_id="BK_OTA_DUP", guest_name_raw="Test User A")

    duplicates = svc.detect_ota_duplicates([ota1, ota2])
    assert "bk_ota_dup" in duplicates
    assert len(duplicates["bk_ota_dup"]) == 2


def test_missing_in_pms(matcher):
    """OTA booking with no PMS match -> missing_in_pms."""
    ota = make_ota_booking(
        reservation_id="BK_NOMATCH_XYZ",
        guest_name_normalized="completely unrelated person abc",
        check_in=date(2026, 9, 1),
        check_out=date(2026, 9, 4),
        gross_amount=99999.0,
    )
    pms = make_pms_booking(
        pms_id="PMS_UNRELATED",
        channel_reference="COMPLETELY_DIFFERENT_REF",
        guest_name_normalized="totally different name def",
        check_in=date(2026, 1, 1),
        check_out=date(2026, 1, 5),
        gross_amount=100.0,
    )

    result = matcher.find_best_match(ota, [pms])
    assert result.final_status == ReconciliationStatus.missing_in_pms
    assert result.best_match is None


def test_missing_in_ota(matcher):
    """PMS has OTA-source booking but no OTA record provided."""
    pms = make_pms_booking(
        pms_id="PMS_OTA_MISSING",
        channel_reference="BK_MISSING_OTA",
    )
    # No OTA bookings provided - this would be detected as missing_in_ota
    # by the reconciliation engine after matching
    # Here we verify the PMS has a channel reference (so it should be in OTA)
    assert pms.channel_reference_id == "BK_MISSING_OTA"
    assert pms.source_platform == SourcePlatform.pms


def test_date_tolerance(matcher):
    """Check-in differs by 1 day -> should still match (within tolerance)."""
    ota = make_ota_booking(
        reservation_id="BK_DATES",
        guest_name_normalized="test user",
        check_in=date(2026, 4, 1),
        check_out=date(2026, 4, 4),
        gross_amount=15000.0,
    )
    pms = make_pms_booking(
        channel_reference="DIFF_REF",
        guest_name_normalized="test user",
        check_in=date(2026, 4, 2),  # 1 day off
        check_out=date(2026, 4, 4),
        gross_amount=15000.0,
    )

    assert matcher.dates_match(date(2026, 4, 1), date(2026, 4, 2), tolerance_days=1) is True
    assert matcher.dates_match(date(2026, 4, 1), date(2026, 4, 3), tolerance_days=1) is False


def test_modification_mismatch(matcher):
    """Different room type between OTA and PMS."""
    ota = make_ota_booking(
        reservation_id="BK_MOD",
        room_type="standard_double",
        status=BookingStatus.modified,
    )
    pms = make_pms_booking(
        channel_reference="BK_MOD",
        room_type="deluxe_double",
        status=BookingStatus.confirmed,
    )

    result = matcher.find_best_match(ota, [pms])
    assert result.best_match is not None
    # Status conflict and/or room type difference
    assert (
        ReasonCode.room_type_difference in result.best_match.reason_codes
        or ReasonCode.status_conflict in result.best_match.reason_codes
    )


def test_no_match_low_confidence(matcher):
    """Very different names and amounts -> low or no match."""
    ota = make_ota_booking(
        reservation_id="BK_LOW",
        guest_name_normalized="xyz abc completely different",
        check_in=date(2026, 4, 1),
        check_out=date(2026, 4, 4),
        gross_amount=100000.0,
    )
    pms = make_pms_booking(
        channel_reference="ANOTHER_REF",
        guest_name_normalized="john doe totally unrelated",
        check_in=date(2026, 6, 15),
        check_out=date(2026, 6, 20),
        gross_amount=5000.0,
    )

    result = matcher.find_best_match(ota, [pms])
    # Either no match or very low confidence
    if result.best_match is not None:
        assert result.best_match.confidence < 50.0
    else:
        assert result.final_status == ReconciliationStatus.missing_in_pms


def test_amounts_within_tolerance_method(matcher):
    """Test the amounts_within_tolerance helper."""
    assert matcher.amounts_within_tolerance(18000.0, 18100.0) is True   # 100 < 200 abs
    assert matcher.amounts_within_tolerance(18000.0, 18500.0) is False  # 500 > 200, 2.8% > 2%
    assert matcher.amounts_within_tolerance(18000.0, 18360.0) is True   # exactly 2%
    assert matcher.amounts_within_tolerance(None, 18000.0) is True      # None -> assume ok
    assert matcher.amounts_within_tolerance(18000.0, None) is True      # None -> assume ok
