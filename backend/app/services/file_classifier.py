from dataclasses import dataclass, field
from typing import List, Dict, Optional
from rapidfuzz import fuzz

from ..schemas.canonical import SourcePlatform


@dataclass
class ClassificationResult:
    source_platform: SourcePlatform
    confidence: float
    method: str  # header_match, pattern_match, content_match
    column_mapping: Dict[str, str] = field(default_factory=dict)


class FileClassifierService:
    """Detects whether a file is from Booking.com, Expedia, or PMS."""

    BOOKING_COM_HEADERS = {
        "booking_number", "reservation_id", "booker_name", "check_in",
        "check_out", "room_nights", "commission", "booking_status",
        "arrival_date", "departure_date", "reservation_number",
        "gross_booking_value", "property_name", "commission_inr",
        "booking number", "property currency", "payment method",
    }

    EXPEDIA_HEADERS = {
        "itinerary_id", "hotel_confirmation_number", "check_in_date",
        "check_out_date", "guest_name", "room_type", "total_amount",
        "expedia_collect", "hotel_collect", "booking_id",
        "itinerary id", "hotel confirmation number", "expedia collect",
        "hotel collect", "payment model",
    }

    PMS_HEADERS = {
        "pms_reservation_id", "reservation_id", "source_channel",
        "ota_reference", "channel_reference", "booking_source",
        "folio_number", "property_id", "ota reference number",
        "pms reservation id", "total revenue", "net revenue",
        "tax amount", "source channel",
    }

    # Distinctive patterns that strongly signal a platform
    BOOKING_COM_STRONG_SIGNALS = {
        "booking_number", "booker_name", "commission_inr",
        "gross_booking_value_inr", "booking number",
    }

    EXPEDIA_STRONG_SIGNALS = {
        "itinerary_id", "expedia_collect", "hotel_collect",
        "itinerary id", "expedia collect", "hotel collect",
    }

    PMS_STRONG_SIGNALS = {
        "pms_reservation_id", "ota_reference", "source_channel",
        "pms reservation id", "ota reference number", "source channel",
    }

    def _normalize_header(self, h: str) -> str:
        return h.lower().strip().replace(" ", "_").replace("-", "_").replace("(", "").replace(")", "")

    def _headers_overlap(self, file_headers_norm: set, platform_headers: set) -> float:
        """Return fraction of platform headers found in file (normalized match)."""
        if not platform_headers:
            return 0.0
        matches = 0
        for ph in platform_headers:
            ph_norm = self._normalize_header(ph)
            for fh in file_headers_norm:
                if ph_norm == fh or fuzz.ratio(ph_norm, fh) >= 85:
                    matches += 1
                    break
        return matches / len(platform_headers)

    def _check_strong_signals(self, file_headers_norm: set, signals: set) -> bool:
        """Return True if any strong signal header is found in file headers."""
        for sig in signals:
            sig_norm = self._normalize_header(sig)
            for fh in file_headers_norm:
                if sig_norm == fh or fuzz.ratio(sig_norm, fh) >= 90:
                    return True
        return False

    def _sample_content_signals(self, sample_rows: List[Dict]) -> Dict[str, int]:
        """Scan sample row values for platform-specific patterns."""
        signals = {"booking_com": 0, "expedia": 0, "pms": 0}
        for row in sample_rows[:5]:
            for val in row.values():
                if val is None:
                    continue
                v = str(val).lower()
                if v.startswith("bk") or "booking.com" in v:
                    signals["booking_com"] += 1
                if v.startswith("exp") or "expedia" in v or v.startswith("it"):
                    signals["expedia"] += 1
                if "pms" in v or v.startswith("pms"):
                    signals["pms"] += 1
        return signals

    def classify(
        self, headers: List[str], sample_rows: List[Dict]
    ) -> ClassificationResult:
        file_headers_norm = {self._normalize_header(h) for h in headers}

        # Check strong signals first
        bc_strong = self._check_strong_signals(file_headers_norm, self.BOOKING_COM_STRONG_SIGNALS)
        exp_strong = self._check_strong_signals(file_headers_norm, self.EXPEDIA_STRONG_SIGNALS)
        pms_strong = self._check_strong_signals(file_headers_norm, self.PMS_STRONG_SIGNALS)

        if bc_strong and not exp_strong and not pms_strong:
            return ClassificationResult(
                source_platform=SourcePlatform.booking_com,
                confidence=0.95,
                method="header_match",
            )
        if exp_strong and not bc_strong and not pms_strong:
            return ClassificationResult(
                source_platform=SourcePlatform.expedia,
                confidence=0.95,
                method="header_match",
            )
        if pms_strong and not bc_strong and not exp_strong:
            return ClassificationResult(
                source_platform=SourcePlatform.pms,
                confidence=0.95,
                method="header_match",
            )

        # Overlap scoring
        bc_overlap = self._headers_overlap(file_headers_norm, self.BOOKING_COM_HEADERS)
        exp_overlap = self._headers_overlap(file_headers_norm, self.EXPEDIA_HEADERS)
        pms_overlap = self._headers_overlap(file_headers_norm, self.PMS_HEADERS)

        scores = {
            SourcePlatform.booking_com: bc_overlap,
            SourcePlatform.expedia: exp_overlap,
            SourcePlatform.pms: pms_overlap,
        }

        best_platform = max(scores, key=scores.__getitem__)
        best_score = scores[best_platform]

        if best_score < 0.15:
            # Try content signals
            content = self._sample_content_signals(sample_rows)
            best_content = max(content, key=content.__getitem__)
            if content[best_content] > 0:
                platform_map = {
                    "booking_com": SourcePlatform.booking_com,
                    "expedia": SourcePlatform.expedia,
                    "pms": SourcePlatform.pms,
                }
                return ClassificationResult(
                    source_platform=platform_map[best_content],
                    confidence=0.40,
                    method="content_match",
                )
            return ClassificationResult(
                source_platform=SourcePlatform.unknown,
                confidence=0.0,
                method="none",
            )

        # Scale confidence: full overlap = 0.95, partial overlap scaled
        confidence = min(0.95, best_score * 0.95)
        return ClassificationResult(
            source_platform=best_platform,
            confidence=confidence,
            method="header_match",
        )
