import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.schemas.canonical import (
    CanonicalBooking, BookingStatus, PaymentType, SourcePlatform
)


@pytest.fixture(scope="function")
def test_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def test_db(test_engine):
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = TestSession()
    yield db
    db.close()


def make_ota_booking(
    reservation_id="BK1001",
    guest_name_raw="Rajesh Kumar",
    guest_name_normalized="rajesh kumar",
    check_in=date(2026, 4, 1),
    check_out=date(2026, 4, 4),
    gross_amount=18000.0,
    status=BookingStatus.confirmed,
    platform=SourcePlatform.booking_com,
    room_type="deluxe_double",
    payment_type=PaymentType.pay_at_hotel,
    nights=3,
) -> CanonicalBooking:
    return CanonicalBooking(
        source_platform=platform,
        external_reservation_id=reservation_id,
        guest_name_raw=guest_name_raw,
        guest_name_normalized=guest_name_normalized,
        check_in_date=check_in,
        check_out_date=check_out,
        number_of_nights=nights,
        gross_amount=gross_amount,
        booking_status=status,
        room_type_normalized=room_type,
        room_type_raw=room_type,
        payment_type=payment_type,
        currency="INR",
        adults=2,
        guest_count=2,
        source_file_name="booking_com_sample.csv",
        source_row_number=1,
    )


def make_pms_booking(
    pms_id="PMS001",
    channel_reference="BK1001",
    guest_name_raw="Rajesh Kumar",
    guest_name_normalized="rajesh kumar",
    check_in=date(2026, 4, 1),
    check_out=date(2026, 4, 4),
    gross_amount=18000.0,
    status=BookingStatus.confirmed,
    room_type="deluxe_double",
    payment_type=PaymentType.pay_at_hotel,
    nights=3,
) -> CanonicalBooking:
    return CanonicalBooking(
        source_platform=SourcePlatform.pms,
        pms_reservation_id=pms_id,
        channel_reference_id=channel_reference,
        guest_name_raw=guest_name_raw,
        guest_name_normalized=guest_name_normalized,
        check_in_date=check_in,
        check_out_date=check_out,
        number_of_nights=nights,
        gross_amount=gross_amount,
        booking_status=status,
        room_type_normalized=room_type,
        room_type_raw=room_type,
        payment_type=payment_type,
        currency="INR",
        adults=2,
        guest_count=2,
        source_file_name="pms_sample.csv",
        source_row_number=1,
    )
