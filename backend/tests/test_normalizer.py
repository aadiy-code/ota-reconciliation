import pytest
from datetime import date

from app.services.normalizer import BookingNormalizerService
from app.schemas.canonical import BookingStatus, PaymentType


@pytest.fixture
def normalizer():
    return BookingNormalizerService()


class TestDateNormalization:
    def test_iso_format(self, normalizer):
        assert normalizer.normalize_date("2026-04-15") == date(2026, 4, 15)

    def test_dd_mm_yyyy(self, normalizer):
        assert normalizer.normalize_date("15/04/2026") == date(2026, 4, 15)

    def test_mm_dd_yyyy(self, normalizer):
        assert normalizer.normalize_date("04/15/2026") == date(2026, 4, 15)

    def test_dd_mm_yyyy_dashes(self, normalizer):
        assert normalizer.normalize_date("15-04-2026") == date(2026, 4, 15)

    def test_dd_mon_yyyy(self, normalizer):
        assert normalizer.normalize_date("15 Apr 2026") == date(2026, 4, 15)

    def test_dd_month_yyyy(self, normalizer):
        assert normalizer.normalize_date("15 April 2026") == date(2026, 4, 15)

    def test_with_time(self, normalizer):
        assert normalizer.normalize_date("2026-04-15T10:30:00") == date(2026, 4, 15)

    def test_with_datetime(self, normalizer):
        from datetime import datetime
        dt = datetime(2026, 4, 15, 10, 30)
        assert normalizer.normalize_date(dt) == date(2026, 4, 15)

    def test_with_date_object(self, normalizer):
        d = date(2026, 4, 15)
        assert normalizer.normalize_date(d) == date(2026, 4, 15)

    def test_none_value(self, normalizer):
        assert normalizer.normalize_date(None) is None

    def test_empty_string(self, normalizer):
        assert normalizer.normalize_date("") is None

    def test_nan_string(self, normalizer):
        assert normalizer.normalize_date("nan") is None

    def test_dd_dot_mm_dot_yyyy(self, normalizer):
        assert normalizer.normalize_date("15.04.2026") == date(2026, 4, 15)


class TestGuestNameNormalization:
    def test_removes_mr(self, normalizer):
        assert normalizer.normalize_guest_name("Mr. Rajesh Kumar") == "rajesh kumar"

    def test_removes_mrs(self, normalizer):
        assert normalizer.normalize_guest_name("Mrs. Priya Sharma") == "priya sharma"

    def test_removes_dr(self, normalizer):
        assert normalizer.normalize_guest_name("Dr. Anil Mehta") == "anil mehta"

    def test_removes_prof(self, normalizer):
        assert normalizer.normalize_guest_name("Prof. Suresh Reddy") == "suresh reddy"

    def test_lowercase(self, normalizer):
        assert normalizer.normalize_guest_name("RAJESH KUMAR") == "rajesh kumar"

    def test_trim_whitespace(self, normalizer):
        assert normalizer.normalize_guest_name("  Rajesh Kumar  ") == "rajesh kumar"

    def test_none_value(self, normalizer):
        assert normalizer.normalize_guest_name(None) == ""

    def test_empty_string(self, normalizer):
        assert normalizer.normalize_guest_name("") == ""

    def test_no_honorific(self, normalizer):
        assert normalizer.normalize_guest_name("Rajesh Kumar") == "rajesh kumar"

    def test_ms_removal(self, normalizer):
        assert normalizer.normalize_guest_name("Ms. Sunita Patel") == "sunita patel"


class TestAmountParsing:
    def test_plain_float(self, normalizer):
        assert normalizer.normalize_amount(18000.0) == 18000.0

    def test_plain_int(self, normalizer):
        assert normalizer.normalize_amount(18000) == 18000.0

    def test_comma_separated(self, normalizer):
        assert normalizer.normalize_amount("1,234.56") == 1234.56

    def test_rupee_symbol(self, normalizer):
        result = normalizer.normalize_amount("₹18000")
        assert result == 18000.0

    def test_inr_prefix(self, normalizer):
        result = normalizer.normalize_amount("INR 18,000.00")
        assert result == 18000.0

    def test_inr_prefix_no_space(self, normalizer):
        result = normalizer.normalize_amount("INR18000")
        assert result == 18000.0

    def test_large_amount_with_comma(self, normalizer):
        assert normalizer.normalize_amount("1,00,000.00") is not None  # Indian format

    def test_none_value(self, normalizer):
        assert normalizer.normalize_amount(None) is None

    def test_empty_string(self, normalizer):
        assert normalizer.normalize_amount("") is None

    def test_nan_string(self, normalizer):
        assert normalizer.normalize_amount("nan") is None

    def test_string_float(self, normalizer):
        assert normalizer.normalize_amount("15000.50") == 15000.50


class TestStatusMappingBookingCom:
    def test_ok_to_confirmed(self, normalizer):
        assert normalizer.normalize_status("ok", "booking_com") == BookingStatus.confirmed

    def test_confirmed(self, normalizer):
        assert normalizer.normalize_status("confirmed", "booking_com") == BookingStatus.confirmed

    def test_cancelled_by_guest(self, normalizer):
        assert normalizer.normalize_status("cancelled_by_guest", "booking_com") == BookingStatus.cancelled

    def test_cancelled_by_hotel(self, normalizer):
        assert normalizer.normalize_status("cancelled_by_hotel", "booking_com") == BookingStatus.cancelled

    def test_no_show(self, normalizer):
        assert normalizer.normalize_status("no_show", "booking_com") == BookingStatus.no_show

    def test_checked_in(self, normalizer):
        assert normalizer.normalize_status("checked_in", "booking_com") == BookingStatus.checked_in

    def test_checked_out(self, normalizer):
        assert normalizer.normalize_status("checked_out", "booking_com") == BookingStatus.checked_out


class TestStatusMappingExpedia:
    def test_booked_to_confirmed(self, normalizer):
        assert normalizer.normalize_status("booked", "expedia") == BookingStatus.confirmed

    def test_confirmed(self, normalizer):
        assert normalizer.normalize_status("confirmed", "expedia") == BookingStatus.confirmed

    def test_cancelled(self, normalizer):
        assert normalizer.normalize_status("cancelled", "expedia") == BookingStatus.cancelled

    def test_no_show(self, normalizer):
        assert normalizer.normalize_status("no_show", "expedia") == BookingStatus.no_show


class TestRoomTypeNormalization:
    def test_none_value(self, normalizer):
        assert normalizer.normalize_room_type(None) is None

    def test_lowercase_conversion(self, normalizer):
        result = normalizer.normalize_room_type("Deluxe Double Room")
        assert result is not None
        assert result == result.lower()

    def test_empty_string(self, normalizer):
        result = normalizer.normalize_room_type("")
        assert result is None


class TestNightsCalculation:
    def test_three_nights(self, normalizer):
        ci = date(2026, 4, 1)
        co = date(2026, 4, 4)
        assert normalizer.calculate_nights(ci, co) == 3

    def test_one_night(self, normalizer):
        ci = date(2026, 4, 1)
        co = date(2026, 4, 2)
        assert normalizer.calculate_nights(ci, co) == 1

    def test_same_day(self, normalizer):
        d = date(2026, 4, 1)
        assert normalizer.calculate_nights(d, d) == 0

    def test_none_check_in(self, normalizer):
        assert normalizer.calculate_nights(None, date(2026, 4, 4)) is None

    def test_none_check_out(self, normalizer):
        assert normalizer.calculate_nights(date(2026, 4, 1), None) is None


class TestPaymentTypeNormalization:
    def test_pay_at_hotel(self, normalizer):
        assert normalizer.normalize_payment_type("pay_at_hotel") == PaymentType.pay_at_hotel

    def test_hotel_collect(self, normalizer):
        assert normalizer.normalize_payment_type("hotel_collect") == PaymentType.pay_at_hotel

    def test_expedia_collect(self, normalizer):
        assert normalizer.normalize_payment_type("expedia_collect") == PaymentType.prepaid

    def test_prepaid(self, normalizer):
        assert normalizer.normalize_payment_type("prepaid") == PaymentType.prepaid

    def test_virtual_card(self, normalizer):
        assert normalizer.normalize_payment_type("virtual_card") == PaymentType.virtual_card

    def test_none_value(self, normalizer):
        assert normalizer.normalize_payment_type(None) == PaymentType.unknown

    def test_unknown_value(self, normalizer):
        assert normalizer.normalize_payment_type("something_random") == PaymentType.unknown
