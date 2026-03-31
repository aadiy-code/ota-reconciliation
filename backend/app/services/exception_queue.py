from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from sqlalchemy.orm import Session

from ..models.db_models import ReconciliationResult, MappingRule, NormalizedBooking
from ..schemas.canonical import ExceptionFilters, ReviewDecisionRequest, ReasonCode
from ..utils.helpers import booking_to_dict
from .audit_logger import AuditLoggerService
from ..utils.helpers import generate_uuid

EXCEPTION_STATUSES = {
    "missing_in_pms",
    "missing_in_ota",
    "duplicate_in_pms",
    "duplicate_in_ota",
    "cancellation_mismatch",
    "modification_mismatch",
    "amount_mismatch",
    "pending_review",
}


@dataclass
class ExceptionRecord:
    result: ReconciliationResult
    ota_booking: Optional[Dict[str, Any]]
    pms_booking: Optional[Dict[str, Any]]


class ExceptionQueueService:
    def __init__(self):
        self.audit = AuditLoggerService()

    def get_exceptions(
        self,
        run_id: str,
        db: Session,
        filters: Optional[ExceptionFilters] = None,
    ) -> List[ReconciliationResult]:
        query = db.query(ReconciliationResult).filter(
            ReconciliationResult.reconciliation_run_id == run_id,
            ReconciliationResult.reconciliation_status.in_(EXCEPTION_STATUSES),
        )

        if filters:
            if filters.status:
                query = query.filter(
                    ReconciliationResult.reconciliation_status == filters.status
                )
            if filters.min_confidence is not None:
                query = query.filter(
                    ReconciliationResult.confidence_score >= filters.min_confidence
                )
            if filters.max_confidence is not None:
                query = query.filter(
                    ReconciliationResult.confidence_score <= filters.max_confidence
                )
            if filters.reason_code:
                # JSON array contains filter (SQLite compatible)
                query = query.filter(
                    ReconciliationResult.reason_codes_json.contains(filters.reason_code)
                )

        return query.order_by(ReconciliationResult.confidence_score.asc()).all()

    def get_pending_review(self, run_id: str, db: Session) -> List[ReconciliationResult]:
        return db.query(ReconciliationResult).filter(
            ReconciliationResult.reconciliation_run_id == run_id,
            ReconciliationResult.review_decision.is_(None),
            ReconciliationResult.reconciliation_status.in_(EXCEPTION_STATUSES),
        ).all()

    def apply_review_decision(
        self,
        result_id: str,
        decision_req: ReviewDecisionRequest,
        db: Session,
    ) -> ReconciliationResult:
        result = db.query(ReconciliationResult).filter(
            ReconciliationResult.id == result_id
        ).first()
        if not result:
            raise ValueError(f"Result {result_id} not found")

        before_state = {
            "review_decision": result.review_decision,
            "review_notes": result.review_notes,
            "reconciliation_status": result.reconciliation_status,
            "is_manual_override": result.is_manual_override,
        }

        result.review_decision = decision_req.decision
        result.review_notes = decision_req.notes
        result.reviewed_by = decision_req.actor
        result.reviewed_at = datetime.utcnow()
        result.is_manual_override = True

        # Update status based on decision
        if decision_req.decision == "accepted":
            result.reconciliation_status = "matched"
        elif decision_req.decision == "marked_variance":
            result.reconciliation_status = "matched_with_minor_variance"
        # "rejected" keeps the original status

        db.commit()

        after_state = {
            "review_decision": result.review_decision,
            "review_notes": result.review_notes,
            "reconciliation_status": result.reconciliation_status,
            "is_manual_override": result.is_manual_override,
        }

        self.audit.log_review_decision(
            result_id=result_id,
            run_id=result.reconciliation_run_id,
            actor=decision_req.actor,
            decision=decision_req.decision,
            before=before_state,
            after=after_state,
            db=db,
        )

        # Optionally create a mapping rule from the decision
        if decision_req.create_rule and decision_req.decision in ("accepted", "marked_variance"):
            self.create_mapping_rule_from_decision(result, decision_req, db)

        return result

    def create_mapping_rule_from_decision(
        self,
        result: ReconciliationResult,
        decision_req: ReviewDecisionRequest,
        db: Session,
    ) -> Optional[MappingRule]:
        """Persist learned mapping from manual review."""
        # If OTA and PMS bookings both exist, we can create name/room-type rules
        ota = None
        pms = None
        if result.ota_booking_id:
            ota = db.query(NormalizedBooking).filter(
                NormalizedBooking.id == result.ota_booking_id
            ).first()
        if result.pms_booking_id:
            pms = db.query(NormalizedBooking).filter(
                NormalizedBooking.id == result.pms_booking_id
            ).first()

        if not ota or not pms:
            return None

        rules_created = []

        # Guest name rule
        if ota.guest_name_normalized != pms.guest_name_normalized:
            rule = MappingRule(
                id=generate_uuid(),
                rule_type="guest_name",
                source_platform=ota.source_platform,
                source_value=ota.guest_name_normalized or "",
                target_value=pms.guest_name_normalized or "",
                confidence=0.9,
                created_from="user_feedback",
            )
            db.add(rule)
            rules_created.append(rule)

        # Room type rule
        if ota.room_type_raw and pms.room_type_raw and ota.room_type_raw != pms.room_type_raw:
            rule = MappingRule(
                id=generate_uuid(),
                rule_type="room_type",
                source_platform=ota.source_platform,
                source_value=(ota.room_type_raw or "").lower(),
                target_value=(pms.room_type_normalized or pms.room_type_raw or "").lower(),
                confidence=0.9,
                created_from="user_feedback",
            )
            db.add(rule)
            rules_created.append(rule)

        if rules_created:
            db.commit()
            for rule in rules_created:
                self.audit.log_mapping_rule_created(
                    rule_id=rule.id,
                    actor=decision_req.actor,
                    rule_data={"rule_type": rule.rule_type, "source": rule.source_value, "target": rule.target_value},
                    db=db,
                )

        return rules_created[0] if rules_created else None
