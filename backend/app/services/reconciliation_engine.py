from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from ..schemas.canonical import (
    CanonicalBooking, ReconciliationStatus, ReasonCode, BookingStatus, SourcePlatform
)
from ..models.db_models import ReconciliationResult, ReconciliationRun, NormalizedBooking
from .matcher import MatchingService, MatchResult, MatchCandidate
from .audit_logger import AuditLoggerService
from ..config import settings


@dataclass
class ReconciliationSummary:
    total_ota_bookings: int
    total_pms_bookings: int
    matched: int
    matched_with_minor_variance: int
    missing_in_pms: int
    missing_in_ota: int
    duplicate_in_pms: int
    duplicate_in_ota: int
    cancellation_mismatch: int
    modification_mismatch: int
    amount_mismatch: int
    source_mismatch: int
    pending_review: int
    match_rate_percent: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_ota_bookings": self.total_ota_bookings,
            "total_pms_bookings": self.total_pms_bookings,
            "matched": self.matched,
            "matched_with_minor_variance": self.matched_with_minor_variance,
            "missing_in_pms": self.missing_in_pms,
            "missing_in_ota": self.missing_in_ota,
            "duplicate_in_pms": self.duplicate_in_pms,
            "duplicate_in_ota": self.duplicate_in_ota,
            "cancellation_mismatch": self.cancellation_mismatch,
            "modification_mismatch": self.modification_mismatch,
            "amount_mismatch": self.amount_mismatch,
            "source_mismatch": self.source_mismatch,
            "pending_review": self.pending_review,
            "match_rate_percent": round(self.match_rate_percent, 2),
        }


class ReconciliationService:
    def __init__(self):
        self.matcher = MatchingService(settings)
        self.audit_logger = AuditLoggerService()

    def run_reconciliation(
        self,
        run_id: str,
        ota_bookings: List[CanonicalBooking],
        pms_bookings: List[CanonicalBooking],
        db: Session,
    ) -> ReconciliationSummary:
        # 1. Detect duplicates before matching
        pms_duplicates = self.detect_pms_duplicates(pms_bookings)
        ota_duplicates = self.detect_ota_duplicates(ota_bookings)

        # Mark duplicate IDs
        dup_pms_ids: set = set()
        for dup_list in pms_duplicates.values():
            if len(dup_list) > 1:
                for b in dup_list:
                    dup_pms_ids.add(b.id)

        dup_ota_ids: set = set()
        for dup_list in ota_duplicates.values():
            if len(dup_list) > 1:
                for b in dup_list:
                    dup_ota_ids.add(b.id)

        # 2. Run matching for all OTA bookings
        match_results: List[MatchResult] = self.matcher.match_all(ota_bookings, pms_bookings)

        matched_pms_ids: set = set()
        db_results: List[ReconciliationResult] = []

        # 3. Process OTA match results
        for mr in match_results:
            ota = mr.ota_booking

            # Override status if duplicate
            if ota.id in dup_ota_ids:
                final_status = ReconciliationStatus.duplicate_in_ota
                reason_codes = [ReasonCode.duplicate_ota_records]
                confidence = 100.0
                matched_rule = "duplicate_detection"
                pms_id = mr.best_match.pms_booking.id if mr.best_match else None
                explanation = self.generate_explanation(ota, mr.best_match.pms_booking if mr.best_match else None,
                                                       final_status, reason_codes)
            else:
                final_status = mr.final_status
                reason_codes = mr.best_match.reason_codes if mr.best_match else [ReasonCode.no_pms_match]
                confidence = mr.best_match.confidence if mr.best_match else 100.0
                matched_rule = mr.best_match.matched_rule if mr.best_match else None
                pms_id = mr.best_match.pms_booking.id if mr.best_match else None
                explanation = self.generate_explanation(
                    ota,
                    mr.best_match.pms_booking if mr.best_match else None,
                    final_status,
                    reason_codes,
                )

            # Override if matched pms is a duplicate
            if pms_id and pms_id in dup_pms_ids:
                final_status = ReconciliationStatus.duplicate_in_pms
                reason_codes = list(set(reason_codes + [ReasonCode.duplicate_pms_records]))

            if pms_id:
                matched_pms_ids.add(pms_id)

            result = ReconciliationResult(
                reconciliation_run_id=run_id,
                ota_booking_id=ota.id,
                pms_booking_id=pms_id,
                reconciliation_status=final_status.value,
                confidence_score=confidence,
                matched_rule=matched_rule,
                reason_codes_json=[rc.value for rc in reason_codes],
                explanation_text=explanation,
            )
            db.add(result)
            db_results.append(result)

        # 4. Find unmatched PMS bookings that have OTA source
        for pms in pms_bookings:
            if pms.id in matched_pms_ids:
                continue
            # Only flag as missing_in_ota if it was an OTA booking
            if pms.source_platform in (SourcePlatform.pms,) and pms.channel_reference_id:
                # PMS booking with OTA reference but no OTA match
                explanation = self.generate_explanation(None, pms, ReconciliationStatus.missing_in_ota, [ReasonCode.no_ota_match])
                result = ReconciliationResult(
                    reconciliation_run_id=run_id,
                    ota_booking_id=None,
                    pms_booking_id=pms.id,
                    reconciliation_status=ReconciliationStatus.missing_in_ota.value,
                    confidence_score=100.0,
                    matched_rule=None,
                    reason_codes_json=[ReasonCode.no_ota_match.value],
                    explanation_text=explanation,
                )
                db.add(result)
                db_results.append(result)

        db.commit()

        # 5. Generate summary
        summary = self.generate_summary(db_results)

        # 6. Update run record
        run = db.query(ReconciliationRun).filter(ReconciliationRun.id == run_id).first()
        if run:
            run.summary_json = summary.to_dict()
            run.status = "completed"
            run.run_completed_at = datetime.utcnow()
            db.commit()

        return summary

    def detect_pms_duplicates(
        self, pms_bookings: List[CanonicalBooking]
    ) -> Dict[str, List[CanonicalBooking]]:
        """Find PMS bookings that share the same OTA reference."""
        groups: Dict[str, List[CanonicalBooking]] = {}
        for b in pms_bookings:
            ref = b.channel_reference_id or b.external_reservation_id
            if ref:
                key = str(ref).lower().strip()
                groups.setdefault(key, []).append(b)
        return {k: v for k, v in groups.items() if len(v) > 1}

    def detect_ota_duplicates(
        self, ota_bookings: List[CanonicalBooking]
    ) -> Dict[str, List[CanonicalBooking]]:
        """Find OTA bookings with duplicate reservation IDs."""
        groups: Dict[str, List[CanonicalBooking]] = {}
        for b in ota_bookings:
            ref = b.external_reservation_id
            if ref:
                key = str(ref).lower().strip()
                groups.setdefault(key, []).append(b)
        return {k: v for k, v in groups.items() if len(v) > 1}

    def generate_explanation(
        self,
        ota: Optional[CanonicalBooking],
        pms: Optional[CanonicalBooking],
        status: ReconciliationStatus,
        reason_codes: List[ReasonCode],
    ) -> str:
        parts = []

        if status == ReconciliationStatus.matched:
            guest = ota.guest_name_raw if ota else "Unknown"
            ci = ota.check_in_date.strftime("%d %b %Y") if (ota and ota.check_in_date) else "?"
            parts.append(f"Booking for {guest} (check-in {ci}) matched perfectly with PMS record.")

        elif status == ReconciliationStatus.matched_with_minor_variance:
            guest = ota.guest_name_raw if ota else "Unknown"
            ci = ota.check_in_date.strftime("%d %b %Y") if (ota and ota.check_in_date) else "?"
            parts.append(f"Booking for {guest} (check-in {ci}) matched with minor differences.")
            if ReasonCode.room_type_difference in reason_codes and ota and pms:
                parts.append(f"Room type: OTA={ota.room_type_raw}, PMS={pms.room_type_raw}.")
            if ReasonCode.guest_name_difference in reason_codes and ota and pms:
                parts.append(f"Name variation: OTA='{ota.guest_name_raw}', PMS='{pms.guest_name_raw}'.")

        elif status == ReconciliationStatus.missing_in_pms:
            guest = ota.guest_name_raw if ota else "Unknown"
            ref = ota.external_reservation_id if ota else "?"
            ci = ota.check_in_date.strftime("%d %b %Y") if (ota and ota.check_in_date) else "?"
            parts.append(f"OTA booking {ref} for {guest} (check-in {ci}) not found in PMS.")
            parts.append("No PMS record matches this reservation.")

        elif status == ReconciliationStatus.missing_in_ota:
            guest = pms.guest_name_raw if pms else "Unknown"
            ref = pms.channel_reference_id or (pms.external_reservation_id if pms else "?")
            parts.append(f"PMS record with OTA reference {ref} for {guest} has no corresponding OTA booking.")
            parts.append("The OTA file does not contain this reservation.")

        elif status == ReconciliationStatus.cancellation_mismatch:
            ota_status = ota.booking_status.value if ota else "?"
            pms_status = pms.booking_status.value if pms else "?"
            guest = ota.guest_name_raw if ota else "Unknown"
            parts.append(f"Cancellation mismatch for {guest}: OTA status={ota_status}, PMS status={pms_status}.")
            parts.append("One side shows cancelled while the other is confirmed.")

        elif status == ReconciliationStatus.amount_mismatch:
            ota_amt = f"INR {ota.gross_amount:,.2f}" if (ota and ota.gross_amount) else "?"
            pms_amt = f"INR {pms.gross_amount:,.2f}" if (pms and pms.gross_amount) else "?"
            guest = ota.guest_name_raw if ota else "Unknown"
            parts.append(f"Amount mismatch for {guest}: OTA={ota_amt}, PMS={pms_amt}.")
            if ota and ota.gross_amount and pms and pms.gross_amount:
                diff = abs(ota.gross_amount - pms.gross_amount)
                parts.append(f"Difference: INR {diff:,.2f} exceeds tolerance.")

        elif status == ReconciliationStatus.modification_mismatch:
            guest = ota.guest_name_raw if ota else "Unknown"
            parts.append(f"Modification mismatch for {guest}: details differ between OTA and PMS.")
            if ReasonCode.room_type_difference in reason_codes and ota and pms:
                parts.append(f"Room type: OTA={ota.room_type_raw}, PMS={pms.room_type_raw}.")

        elif status == ReconciliationStatus.duplicate_in_pms:
            ref = (pms.channel_reference_id or pms.external_reservation_id) if pms else "?"
            parts.append(f"Duplicate PMS records found for OTA reference {ref}.")
            parts.append("Multiple PMS entries share the same OTA booking reference.")

        elif status == ReconciliationStatus.duplicate_in_ota:
            ref = ota.external_reservation_id if ota else "?"
            parts.append(f"Duplicate OTA records found for reservation {ref}.")

        elif status == ReconciliationStatus.pending_review:
            guest = ota.guest_name_raw if ota else "Unknown"
            parts.append(f"Booking for {guest} requires manual review.")
            if reason_codes:
                code_strs = ", ".join(rc.value.replace("_", " ") for rc in reason_codes)
                parts.append(f"Issues: {code_strs}.")

        return " ".join(parts)

    def generate_summary(self, results: List[ReconciliationResult]) -> ReconciliationSummary:
        counts: Dict[str, int] = {}
        ota_ids = set()
        pms_ids = set()

        for r in results:
            s = r.reconciliation_status
            counts[s] = counts.get(s, 0) + 1
            if r.ota_booking_id:
                ota_ids.add(r.ota_booking_id)
            if r.pms_booking_id:
                pms_ids.add(r.pms_booking_id)

        total_ota = len(ota_ids)
        total_pms = len(pms_ids)
        matched = counts.get("matched", 0) + counts.get("matched_with_minor_variance", 0)
        match_rate = (matched / total_ota * 100) if total_ota > 0 else 0.0

        return ReconciliationSummary(
            total_ota_bookings=total_ota,
            total_pms_bookings=total_pms,
            matched=counts.get("matched", 0),
            matched_with_minor_variance=counts.get("matched_with_minor_variance", 0),
            missing_in_pms=counts.get("missing_in_pms", 0),
            missing_in_ota=counts.get("missing_in_ota", 0),
            duplicate_in_pms=counts.get("duplicate_in_pms", 0),
            duplicate_in_ota=counts.get("duplicate_in_ota", 0),
            cancellation_mismatch=counts.get("cancellation_mismatch", 0),
            modification_mismatch=counts.get("modification_mismatch", 0),
            amount_mismatch=counts.get("amount_mismatch", 0),
            source_mismatch=counts.get("source_mismatch", 0),
            pending_review=counts.get("pending_review", 0),
            match_rate_percent=match_rate,
        )
