import re
import unicodedata
from datetime import date, datetime
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session

from ..schemas.canonical import (
    BookingStatus, PaymentType, SourcePlatform, CanonicalBooking
)
from ..models.db_models import MappingRule

HONORIFICS = {
    "mr", "mrs", "ms", "miss", "dr", "prof", "sir", "madam", "rev",
    "capt", "major", "col", "gen", "sgt", "cpl", "pvt", "mx",
    "er", "shri", "smt",
}

DATE_FORMATS = [
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y",
    "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y",
    "%b %d %Y", "%B %d %Y",
    "%Y/%m/%d", "%d.%m.%Y", "%Y%m%d",
]

BOOKING_COM_STATUS_MAP = {
    "ok": "confirmed",
    "confirmed": "confirmed",
    "cancelled_by_guest": "cancelled",
    "cancelled_by_hotel": "cancelled",
    "cancelled": "cancelled",
    "modified": "modified",
    "no_show": "no_show",
    "no-show": "no_show",
    "checked_in": "checked_in",
    "checked in": "checked_in",
    "checked_out": "checked_out",
    "checked out": "checked_out",
    "pending": "confirmed",
    "valid": "confirmed",
}

EXPEDIA_STATUS_MAP = {
    "booked": "confirmed",
    "confirmed": "confirmed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "modified": "modified",
    "no_show": "no_show",
    "no-show": "no_show",
    "checked_in": "checked_in",
    "checked_out": "checked_out",
}

PMS_STATUS_MAP = {
    "confirmed": "confirmed",
    "reserved": "confirmed",
    "checked_in": "checked_in",
    "in_house": "checked_in",
    "checked_out": "checked_out",
    "departed": "checked_out",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "no_show": "no_show",
    "no-show": "no_show",
    "modified": "modified",
}

PAYMENT_TYPE_MAP = {
    "pay_at_hotel": PaymentType.pay_at_hotel,
    "pay at hotel": PaymentType.pay_at_hotel,
    "hotel_collect": PaymentType.pay_at_hotel,
    "hotel collect": PaymentType.pay_at_hotel,
    "direct": PaymentType.pay_at_hotel,
    "prepaid": PaymentType.prepaid,
    "expedia_collect": PaymentType.prepaid,
    "expedia collect": PaymentType.prepaid,
    "ota_collect": PaymentType.prepaid,
    "ota collect": PaymentType.prepaid,
    "online": PaymentType.prepaid,
    "card": PaymentType.prepaid,
    "virtual_card": PaymentType.virtual_card,
    "virtual card": PaymentType.virtual_card,
    "vcc": PaymentType.virtual_card,
    "bv": PaymentType.virtual_card,  # Booking.com virtual
}


class BookingNormalizerService:
    def __init__(self, db: Optional[Session] = None):
        self.db = db
        self._room_type_rules: Optional[List[MappingRule]] = None

    def _load_room_type_rules(self) -> List[MappingRule]:
        if self._room_type_rules is None and self.db is not None:
            self._room_type_rules = self.db.query(MappingRule).filter(
                MappingRule.rule_type == "room_type"
            ).all()
        return self._room_type_rules or []

    def normalize_guest_name(self, name: Optional[str]) -> str:
        if not name:
            return ""
        # Unicode normalize
        name = unicodedata.normalize("NFC", name)
        # Remove honorifics
        parts = re.split(r"[\s,]+", name.strip())
        cleaned = []
        for part in parts:
            clean_part = re.sub(r"[^a-zA-Z\-']", "", part)
            if clean_part.lower().rstrip(".") not in HONORIFICS:
                if clean_part:
                    cleaned.append(clean_part)
        result = " ".join(cleaned).lower().strip()
        return result

    def normalize_date(self, value: Any) -> Optional[date]:
        if value is None:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        s = str(value).strip()
        if not s or s.lower() in ("nan", "none", "null", ""):
            return None
        # Remove time portion if present (only strip if there's a time component after T or space-HH:MM pattern)
        if "T" in s:
            s = s.split("T")[0]
        elif re.search(r"\s+\d{2}:\d{2}", s):
            s = re.split(r"\s+\d{2}:\d{2}", s)[0]
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    def normalize_amount(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value) if not (value != value) else None  # NaN check
        s = str(value).strip()
        if not s or s.lower() in ("nan", "none", "null", ""):
            return None
        # Remove currency symbols and codes
        s = re.sub(r"[₹$€£¥]", "", s)
        s = re.sub(r"(INR|USD|EUR|GBP|AED)\s*", "", s, flags=re.IGNORECASE)
        s = s.strip()
        # Remove thousands separators (handle both 1,234.56 and 1.234,56)
        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):
                # European format: 1.234,56
                s = s.replace(".", "").replace(",", ".")
            else:
                # US format: 1,234.56
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(",", "")
        s = s.strip()
        try:
            return float(s)
        except ValueError:
            return None

    def normalize_status(self, value: Any, platform: str) -> BookingStatus:
        if not value:
            return BookingStatus.unknown
        s = str(value).lower().strip().replace(" ", "_")
        status_map = {
            "booking_com": BOOKING_COM_STATUS_MAP,
            "expedia": EXPEDIA_STATUS_MAP,
            "pms": PMS_STATUS_MAP,
        }.get(platform, {})

        canonical = status_map.get(s) or status_map.get(s.replace("_", " "))
        if not canonical:
            # Fallback generic
            if "cancel" in s:
                return BookingStatus.cancelled
            if "no_show" in s or "noshow" in s:
                return BookingStatus.no_show
            if "check" in s and "in" in s:
                return BookingStatus.checked_in
            if "check" in s and "out" in s:
                return BookingStatus.checked_out
            if "modif" in s or "amend" in s:
                return BookingStatus.modified
            if "confirm" in s or "ok" in s or "valid" in s or "book" in s:
                return BookingStatus.confirmed
            return BookingStatus.unknown

        try:
            return BookingStatus(canonical)
        except ValueError:
            return BookingStatus.unknown

    def normalize_room_type(self, value: Optional[str], hotel_id: Optional[str] = None) -> Optional[str]:
        if not value:
            return None
        normalized = value.lower().strip()
        rules = self._load_room_type_rules()
        for rule in rules:
            if rule.source_value and rule.source_value.lower() == normalized:
                return rule.target_value
        # Basic normalization
        normalized = re.sub(r"\s+", "_", normalized)
        normalized = re.sub(r"[^a-z0-9_]", "", normalized)
        return normalized or value.lower().strip()

    def normalize_payment_type(self, value: Optional[str]) -> PaymentType:
        if not value:
            return PaymentType.unknown
        s = str(value).lower().strip()
        result = PAYMENT_TYPE_MAP.get(s)
        if result:
            return result
        # Partial matching
        if "hotel" in s and "collect" in s:
            return PaymentType.pay_at_hotel
        if "virtual" in s or "vcc" in s:
            return PaymentType.virtual_card
        if "prepaid" in s or "expedia" in s or "ota" in s or "online" in s:
            return PaymentType.prepaid
        return PaymentType.unknown

    def calculate_nights(self, check_in: Optional[date], check_out: Optional[date]) -> Optional[int]:
        if check_in is None or check_out is None:
            return None
        delta = (check_out - check_in).days
        return max(0, delta)

    def normalize_booking(
        self,
        raw_row: Dict[str, Any],
        column_mapping: Dict[str, str],
        source_platform: str,
        source_file_name: str = "",
        source_row_number: int = 0,
        reconciliation_run_id: Optional[str] = None,
        file_id: Optional[str] = None,
    ) -> CanonicalBooking:
        """Apply all normalization rules and return a CanonicalBooking."""
        # Invert mapping: canonical_field -> source_col
        canonical_to_source: Dict[str, str] = {v: k for k, v in column_mapping.items()}

        def get_val(canonical_field: str) -> Any:
            source_col = canonical_to_source.get(canonical_field)
            if source_col and source_col in raw_row:
                return raw_row[source_col]
            # Try direct key match
            if canonical_field in raw_row:
                return raw_row[canonical_field]
            return None

        check_in = self.normalize_date(get_val("check_in_date"))
        check_out = self.normalize_date(get_val("check_out_date"))
        nights = self.calculate_nights(check_in, check_out)

        guest_name_raw = str(get_val("guest_name_raw") or "").strip()
        guest_name_norm = self.normalize_guest_name(guest_name_raw)

        raw_status = get_val("booking_status")
        booking_status = self.normalize_status(raw_status, source_platform)

        raw_payment = get_val("payment_type")
        payment_type = self.normalize_payment_type(raw_payment)

        room_type_raw_val = get_val("room_type_raw")
        room_type_raw = str(room_type_raw_val).strip() if room_type_raw_val else None
        room_type_norm = self.normalize_room_type(room_type_raw)

        gross = self.normalize_amount(get_val("gross_amount"))
        net = self.normalize_amount(get_val("net_amount"))
        taxes = self.normalize_amount(get_val("taxes_and_fees"))
        commission = self.normalize_amount(get_val("commission_amount"))

        adults_val = get_val("adults")
        children_val = get_val("children")
        guest_count_val = get_val("guest_count")

        try:
            adults = int(adults_val) if adults_val is not None and str(adults_val).strip() not in ("", "nan") else None
        except (ValueError, TypeError):
            adults = None
        try:
            children = int(children_val) if children_val is not None and str(children_val).strip() not in ("", "nan") else None
        except (ValueError, TypeError):
            children = None
        try:
            guest_count = int(guest_count_val) if guest_count_val is not None and str(guest_count_val).strip() not in ("", "nan") else None
        except (ValueError, TypeError):
            guest_count = None

        if guest_count is None and adults is not None:
            guest_count = adults + (children or 0)

        currency_val = get_val("currency")
        currency = str(currency_val).strip().upper() if currency_val else "INR"
        if not currency or currency.lower() in ("nan", "none"):
            currency = "INR"

        ext_res_id = get_val("external_reservation_id")
        pms_res_id = get_val("pms_reservation_id")
        channel_ref_id = get_val("channel_reference_id")

        # Convert to string if present
        def to_str(v: Any) -> Optional[str]:
            if v is None:
                return None
            s = str(v).strip()
            return s if s and s.lower() not in ("nan", "none", "null") else None

        return CanonicalBooking(
            reconciliation_run_id=reconciliation_run_id,
            file_id=file_id,
            source_platform=SourcePlatform(source_platform) if source_platform in SourcePlatform._value2member_map_ else SourcePlatform.unknown,
            hotel_id=to_str(get_val("hotel_id")),
            external_reservation_id=to_str(ext_res_id),
            pms_reservation_id=to_str(pms_res_id),
            channel_reference_id=to_str(channel_ref_id),
            booking_status=booking_status,
            guest_name_raw=guest_name_raw,
            guest_name_normalized=guest_name_norm,
            check_in_date=check_in,
            check_out_date=check_out,
            number_of_nights=nights,
            booking_date=self.normalize_date(get_val("booking_date")),
            room_type_raw=room_type_raw,
            room_type_normalized=room_type_norm,
            guest_count=guest_count,
            adults=adults,
            children=children,
            currency=currency,
            gross_amount=gross,
            net_amount=net,
            taxes_and_fees=taxes,
            commission_amount=commission,
            payment_type=payment_type,
            source_file_name=source_file_name,
            source_row_number=source_row_number,
            raw_payload_json=raw_row,
        )
