from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from ..models.db_models import AuditLog
from ..utils.helpers import generate_uuid


class AuditLoggerService:
    def log(
        self,
        action: str,
        actor: str,
        db: Session,
        reconciliation_run_id: Optional[str] = None,
        result_id: Optional[str] = None,
        before_state: Optional[Dict[str, Any]] = None,
        after_state: Optional[Dict[str, Any]] = None,
    ) -> AuditLog:
        entry = AuditLog(
            id=generate_uuid(),
            reconciliation_run_id=reconciliation_run_id,
            result_id=result_id,
            action=action,
            actor=actor,
            before_state_json=before_state,
            after_state_json=after_state,
            created_at=datetime.utcnow(),
        )
        db.add(entry)
        db.commit()
        return entry

    def log_run_started(self, run_id: str, triggered_by: str, db: Session) -> None:
        self.log(
            action="reconciliation_run_started",
            actor=triggered_by,
            db=db,
            reconciliation_run_id=run_id,
            after_state={"run_id": run_id, "triggered_by": triggered_by},
        )

    def log_run_completed(self, run_id: str, summary: Dict[str, Any], db: Session) -> None:
        self.log(
            action="reconciliation_run_completed",
            actor="system",
            db=db,
            reconciliation_run_id=run_id,
            after_state={"run_id": run_id, "summary": summary},
        )

    def log_review_decision(
        self,
        result_id: str,
        run_id: str,
        actor: str,
        decision: str,
        before: Dict[str, Any],
        after: Dict[str, Any],
        db: Session,
    ) -> None:
        self.log(
            action=f"review_decision_{decision}",
            actor=actor,
            db=db,
            reconciliation_run_id=run_id,
            result_id=result_id,
            before_state=before,
            after_state=after,
        )

    def log_mapping_rule_created(
        self, rule_id: str, actor: str, rule_data: Dict[str, Any], db: Session
    ) -> None:
        self.log(
            action="mapping_rule_created",
            actor=actor,
            db=db,
            after_state={"rule_id": rule_id, **rule_data},
        )

    def log_mapping_rule_deleted(
        self, rule_id: str, actor: str, rule_data: Dict[str, Any], db: Session
    ) -> None:
        self.log(
            action="mapping_rule_deleted",
            actor=actor,
            db=db,
            before_state={"rule_id": rule_id, **rule_data},
        )
