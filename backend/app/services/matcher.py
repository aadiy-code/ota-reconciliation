from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Dict
from rapidfuzz import fuzz

from ..schemas.canonical import (
    CanonicalBooking, ReconciliationStatus, ReasonCode, BookingStatus
)
from ..config import Settings, settings as default_settings


@dataclass
class MatchCandidate:
    pms_booking: CanonicalBooking
    confidence: float
    matched_rule: str  # "exact_reference", "exact_structured", "fuzzy", "weak"
    field_scores: Dict[str, float] = field(default_factory=dict)
    reason_codes: List[ReasonCode] = field(default_factory=list)


@dataclass
class MatchResult:
    ota_booking: CanonicalBooking
    best_match: Optional[MatchCandidate]
    all_candidates: List[MatchCandidate]
    final_status: ReconciliationStatus
    needs_review: bool


class MatchingService:
    def __init__(self, settings: Optional[Settings] = None):
        cfg = settings or default_settings
        self.name_auto_threshold = cfg.NAME_AUTO_MATCH_THRESHOLD * 100  # rapidfuzz uses 0-100
        self.name_review_threshold = cfg.NAME_MANUAL_REVIEW_THRESHOLD * 100
        self.amount_tolerance_abs = cfg.AMOUNT_TOLERANCE_ABSOLUTE
        self.amount_tolerance_pct = cfg.AMOUNT_TOLERANCE_PERCENT
        self.date_tolerance_days = cfg.DATE_TOLERANCE_DAYS
        self.high_confidence_threshold = cfg.HIGH_CONFIDENCE_THRESHOLD
        self.manual_review_threshold = cfg.MANUAL_REVIEW_THRESHOLD

    def match_all(
        self,
        ota_bookings: List[CanonicalBooking],
        pms_bookings: List[CanonicalBooking],
    ) -> List[MatchResult]:
        results = []
        used_pms_ids: set = set()

        for ota in ota_bookings:
            result = self.find_best_match(ota, pms_bookings, used_pms_ids)
            if result.best_match is not None:
                used_pms_ids.add(result.best_match.pms_booking.id)
            results.append(result)

        return results

    def find_best_match(
        self,
        ota: CanonicalBooking,
        pms_candidates: List[CanonicalBooking],
        used_ids: Optional[set] = None,
    ) -> MatchResult:
        if used_ids is None:
            used_ids = set()

        available_pms = [p for p in pms_candidates if p.id not in used_ids]

        # Priority 1: Exact reference match
        exact_ref = self.try_exact_reference_match(ota, available_pms)
        if exact_ref is not None:
            final_status = self._determine_status(ota, exact_ref)
            needs_review = self._needs_review(exact_ref.confidence, final_status)
            return MatchResult(
                ota_booking=ota,
                best_match=exact_ref,
                all_candidates=[exact_ref],
                final_status=final_status,
                needs_review=needs_review,
            )

        # Priority 2: Exact structured match
        exact_struct = self.try_exact_structured_match(ota, available_pms)
        if exact_struct is not None:
            final_status = self._determine_status(ota, exact_struct)
            needs_review = self._needs_review(exact_struct.confidence, final_status)
            return MatchResult(
                ota_booking=ota,
                best_match=exact_struct,
                all_candidates=[exact_struct],
                final_status=final_status,
                needs_review=needs_review,
            )

        # Priority 3: Fuzzy matching — only accept if confidence meets manual review threshold
        fuzzy_candidates = self.try_fuzzy_match(ota, available_pms)
        if fuzzy_candidates:
            best = fuzzy_candidates[0]
            name_sim = self.calculate_name_similarity(
                ota.guest_name_normalized or "",
                best.pms_booking.guest_name_normalized or "",
            )
            # Reject weak fuzzy matches — must meet minimum confidence AND name threshold
            if best.confidence >= self.manual_review_threshold and name_sim >= self.name_review_threshold:
                final_status = self._determine_status(ota, best)
                needs_review = self._needs_review(best.confidence, final_status)
                return MatchResult(
                    ota_booking=ota,
                    best_match=best,
                    all_candidates=fuzzy_candidates,
                    final_status=final_status,
                    needs_review=needs_review,
                )

        # No match found
        return MatchResult(
            ota_booking=ota,
            best_match=None,
            all_candidates=[],
            final_status=ReconciliationStatus.missing_in_pms,
            needs_review=True,
        )

    def try_exact_reference_match(
        self, ota: CanonicalBooking, pms_list: List[CanonicalBooking]
    ) -> Optional[MatchCandidate]:
        """Priority 1: Match on external_reservation_id == pms.channel_reference_id"""
        ota_ref = ota.external_reservation_id
        if not ota_ref:
            return None

        for pms in pms_list:
            pms_refs = [
                pms.channel_reference_id,
                pms.external_reservation_id,
            ]
            for ref in pms_refs:
                if ref and str(ref).strip().lower() == str(ota_ref).strip().lower():
                    reason_codes = []
                    field_scores = {"reference_id": 100.0}

                    # Check for variances
                    amount_match = self._check_amount_variance(ota, pms, reason_codes)
                    status_match = self._check_status_variance(ota, pms, reason_codes)
                    date_match = self._check_date_variance(ota, pms, reason_codes)
                    self._check_room_type_variance(ota, pms, reason_codes)

                    confidence = 100.0
                    return MatchCandidate(
                        pms_booking=pms,
                        confidence=confidence,
                        matched_rule="exact_reference",
                        field_scores=field_scores,
                        reason_codes=reason_codes,
                    )
        return None

    def try_exact_structured_match(
        self, ota: CanonicalBooking, pms_list: List[CanonicalBooking]
    ) -> Optional[MatchCandidate]:
        """Priority 2: Match on dates + name (exact/very close) + amount within tolerance."""
        best: Optional[MatchCandidate] = None
        best_conf = 0.0

        for pms in pms_list:
            field_scores: Dict[str, float] = {}
            reason_codes: List[ReasonCode] = []

            # Date match (strict)
            ci_match = self.dates_match(ota.check_in_date, pms.check_in_date, 0)
            co_match = self.dates_match(ota.check_out_date, pms.check_out_date, 0)
            if not ci_match or not co_match:
                continue

            field_scores["check_in"] = 100.0 if ci_match else 0.0
            field_scores["check_out"] = 100.0 if co_match else 0.0

            # Name similarity
            name_score = self.calculate_name_similarity(
                ota.guest_name_normalized or "",
                pms.guest_name_normalized or "",
            )
            field_scores["guest_name"] = name_score
            if name_score < self.name_review_threshold:
                reason_codes.append(ReasonCode.guest_name_difference)
                continue  # Names too different for structured match

            # Amount check
            amount_ok = self._check_amount_variance(ota, pms, reason_codes)
            if ota.gross_amount is not None and pms.gross_amount is not None:
                field_scores["amount"] = 100.0 if amount_ok else 60.0

            # Status variance check
            self._check_status_variance(ota, pms, reason_codes)
            self._check_room_type_variance(ota, pms, reason_codes)

            # Confidence calculation
            name_conf = min(100.0, name_score)
            amount_penalty = 0.0 if amount_ok else 10.0
            status_penalty = 5.0 if ReasonCode.status_conflict in reason_codes else 0.0

            confidence = 90.0 - amount_penalty - status_penalty
            if name_score >= self.name_auto_threshold:
                confidence = min(confidence, 90.0)
            elif name_score >= self.name_review_threshold:
                confidence = min(confidence, 80.0)

            if confidence > best_conf:
                best_conf = confidence
                best = MatchCandidate(
                    pms_booking=pms,
                    confidence=confidence,
                    matched_rule="exact_structured",
                    field_scores=field_scores,
                    reason_codes=reason_codes[:],
                )

        return best

    def try_fuzzy_match(
        self, ota: CanonicalBooking, pms_list: List[CanonicalBooking]
    ) -> List[MatchCandidate]:
        """Priority 3: Fuzzy match with scoring."""
        candidates: List[MatchCandidate] = []

        for pms in pms_list:
            field_scores: Dict[str, float] = {}
            reason_codes: List[ReasonCode] = []

            # Name score
            name_score = self.calculate_name_similarity(
                ota.guest_name_normalized or "",
                pms.guest_name_normalized or "",
            )
            field_scores["guest_name"] = name_score

            # Date scores
            ci_exact = self.dates_match(ota.check_in_date, pms.check_in_date, 0)
            ci_fuzzy = self.dates_match(ota.check_in_date, pms.check_in_date, self.date_tolerance_days)
            co_exact = self.dates_match(ota.check_out_date, pms.check_out_date, 0)
            co_fuzzy = self.dates_match(ota.check_out_date, pms.check_out_date, self.date_tolerance_days)

            ci_score = 100.0 if ci_exact else (80.0 if ci_fuzzy else 0.0)
            co_score = 100.0 if co_exact else (80.0 if co_fuzzy else 0.0)
            field_scores["check_in"] = ci_score
            field_scores["check_out"] = co_score

            if not ci_fuzzy and not co_fuzzy and ci_score == 0 and co_score == 0:
                reason_codes.append(ReasonCode.date_difference)
            elif not ci_exact or not co_exact:
                reason_codes.append(ReasonCode.date_difference)

            # Amount score
            amount_ok = self._check_amount_variance(ota, pms, reason_codes)
            if ota.gross_amount is not None and pms.gross_amount is not None:
                field_scores["amount"] = 100.0 if amount_ok else 40.0

            # Status
            self._check_status_variance(ota, pms, reason_codes)
            self._check_room_type_variance(ota, pms, reason_codes)

            # Weighted confidence
            weights = {"guest_name": 0.35, "check_in": 0.25, "check_out": 0.25, "amount": 0.15}
            total_weight = 0.0
            weighted_sum = 0.0
            for field, weight in weights.items():
                if field in field_scores:
                    weighted_sum += field_scores[field] * weight
                    total_weight += weight
            if total_weight > 0:
                confidence = weighted_sum / total_weight
            else:
                confidence = 0.0

            # Apply penalties
            if ReasonCode.status_conflict in reason_codes:
                confidence -= 5.0
            if ReasonCode.guest_name_difference in reason_codes or name_score < self.name_review_threshold:
                confidence -= 10.0

            confidence = max(0.0, min(85.0, confidence))

            if confidence >= 40.0:  # Minimum threshold to include as candidate
                if name_score < self.name_review_threshold:
                    reason_codes.append(ReasonCode.guest_name_difference)
                if confidence < self.manual_review_threshold:
                    reason_codes.append(ReasonCode.low_confidence_match)

                candidates.append(MatchCandidate(
                    pms_booking=pms,
                    confidence=confidence,
                    matched_rule="fuzzy",
                    field_scores=field_scores,
                    reason_codes=list(set(reason_codes)),
                ))

        candidates.sort(key=lambda c: -c.confidence)
        return candidates[:5]  # Return top 5 candidates

    def calculate_name_similarity(self, name1: str, name2: str) -> float:
        if not name1 or not name2:
            return 0.0
        # Use token_sort_ratio to handle "Smith John" vs "John Smith"
        return float(fuzz.token_sort_ratio(name1, name2))

    def amounts_within_tolerance(self, amount1: Optional[float], amount2: Optional[float]) -> bool:
        if amount1 is None or amount2 is None:
            return True  # Can't compare, assume ok
        diff = abs(amount1 - amount2)
        avg = (abs(amount1) + abs(amount2)) / 2
        pct_diff = diff / avg if avg > 0 else 0.0
        return diff <= self.amount_tolerance_abs or pct_diff <= self.amount_tolerance_pct

    def dates_match(
        self,
        date1: Optional[date],
        date2: Optional[date],
        tolerance_days: int = 0,
    ) -> bool:
        if date1 is None or date2 is None:
            return False
        diff = abs((date1 - date2).days)
        return diff <= tolerance_days

    def _check_amount_variance(
        self,
        ota: CanonicalBooking,
        pms: CanonicalBooking,
        reason_codes: List[ReasonCode],
    ) -> bool:
        if ota.gross_amount is None or pms.gross_amount is None:
            return True
        ok = self.amounts_within_tolerance(ota.gross_amount, pms.gross_amount)
        if not ok and ReasonCode.amount_difference not in reason_codes:
            reason_codes.append(ReasonCode.amount_difference)
        return ok

    def _check_status_variance(
        self,
        ota: CanonicalBooking,
        pms: CanonicalBooking,
        reason_codes: List[ReasonCode],
    ) -> bool:
        if ota.booking_status == pms.booking_status:
            return True
        # Some status combos are expected
        ok_combos = {
            (BookingStatus.confirmed, BookingStatus.checked_in),
            (BookingStatus.confirmed, BookingStatus.checked_out),
            (BookingStatus.checked_in, BookingStatus.confirmed),
            (BookingStatus.checked_out, BookingStatus.confirmed),
            (BookingStatus.checked_out, BookingStatus.checked_in),
        }
        if (ota.booking_status, pms.booking_status) in ok_combos:
            return True
        if ReasonCode.status_conflict not in reason_codes:
            reason_codes.append(ReasonCode.status_conflict)
        return False

    def _check_date_variance(
        self,
        ota: CanonicalBooking,
        pms: CanonicalBooking,
        reason_codes: List[ReasonCode],
    ) -> bool:
        ci_ok = self.dates_match(ota.check_in_date, pms.check_in_date, 0)
        co_ok = self.dates_match(ota.check_out_date, pms.check_out_date, 0)
        if not ci_ok or not co_ok:
            if ReasonCode.date_difference not in reason_codes:
                reason_codes.append(ReasonCode.date_difference)
            return False
        return True

    def _check_room_type_variance(
        self,
        ota: CanonicalBooking,
        pms: CanonicalBooking,
        reason_codes: List[ReasonCode],
    ) -> bool:
        ota_rt = ota.room_type_normalized
        pms_rt = pms.room_type_normalized
        if not ota_rt or not pms_rt:
            return True
        if ota_rt.lower() == pms_rt.lower():
            return True
        if ReasonCode.room_type_difference not in reason_codes:
            reason_codes.append(ReasonCode.room_type_difference)
        return False

    def _determine_status(
        self, ota: CanonicalBooking, match: MatchCandidate
    ) -> ReconciliationStatus:
        if not match.reason_codes:
            return ReconciliationStatus.matched

        codes = set(match.reason_codes)

        # Cancellation mismatch
        ota_cancelled = ota.booking_status == BookingStatus.cancelled
        pms_cancelled = match.pms_booking.booking_status == BookingStatus.cancelled
        if ReasonCode.status_conflict in codes:
            if ota_cancelled != pms_cancelled:
                return ReconciliationStatus.cancellation_mismatch
            if ota.room_type_normalized != match.pms_booking.room_type_normalized:
                return ReconciliationStatus.modification_mismatch

        if ReasonCode.amount_difference in codes:
            return ReconciliationStatus.amount_mismatch

        # Minor variances only
        minor_codes = {
            ReasonCode.room_type_difference,
            ReasonCode.guest_name_difference,
            ReasonCode.low_confidence_match,
        }
        if codes.issubset(minor_codes):
            if match.confidence >= self.high_confidence_threshold:
                return ReconciliationStatus.matched_with_minor_variance
            return ReconciliationStatus.pending_review

        if match.confidence < self.manual_review_threshold:
            return ReconciliationStatus.pending_review

        return ReconciliationStatus.matched_with_minor_variance

    def _needs_review(self, confidence: float, status: ReconciliationStatus) -> bool:
        review_statuses = {
            ReconciliationStatus.pending_review,
            ReconciliationStatus.cancellation_mismatch,
            ReconciliationStatus.amount_mismatch,
            ReconciliationStatus.modification_mismatch,
        }
        if status in review_statuses:
            return True
        if confidence < self.high_confidence_threshold:
            return True
        return False
