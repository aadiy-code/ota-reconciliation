from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.db_models import MappingRule
from ...schemas.canonical import MappingRuleCreate, MappingRuleResponse
from ...services.feedback_store import FeedbackStoreService
from ...services.audit_logger import AuditLoggerService
from ...utils.helpers import generate_uuid
from datetime import datetime

router = APIRouter(prefix="/api/v1/mapping-rules", tags=["mapping-rules"])

feedback_svc = FeedbackStoreService()
audit_svc = AuditLoggerService()


@router.get("", response_model=List[MappingRuleResponse])
def list_mapping_rules(
    rule_type: Optional[str] = None,
    source_platform: Optional[str] = None,
    hotel_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    rules = feedback_svc.get_rules(db, hotel_id=hotel_id, rule_type=rule_type, source_platform=source_platform)
    return [
        MappingRuleResponse(
            id=r.id,
            hotel_id=r.hotel_id,
            rule_type=r.rule_type,
            source_platform=r.source_platform,
            source_value=r.source_value,
            target_value=r.target_value,
            confidence=r.confidence,
            created_from=r.created_from,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rules
    ]


@router.post("", response_model=MappingRuleResponse)
def create_mapping_rule(
    body: MappingRuleCreate,
    actor: str = "user",
    db: Session = Depends(get_db),
):
    rule = feedback_svc.add_rule(
        db=db,
        rule_type=body.rule_type,
        source_value=body.source_value,
        target_value=body.target_value,
        source_platform=body.source_platform,
        hotel_id=body.hotel_id,
        confidence=body.confidence,
        created_from=body.created_from,
    )
    audit_svc.log_mapping_rule_created(
        rule_id=rule.id,
        actor=actor,
        rule_data={
            "rule_type": rule.rule_type,
            "source": rule.source_value,
            "target": rule.target_value,
        },
        db=db,
    )
    return MappingRuleResponse(
        id=rule.id,
        hotel_id=rule.hotel_id,
        rule_type=rule.rule_type,
        source_platform=rule.source_platform,
        source_value=rule.source_value,
        target_value=rule.target_value,
        confidence=rule.confidence,
        created_from=rule.created_from,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


@router.delete("/{rule_id}")
def delete_mapping_rule(
    rule_id: str,
    actor: str = "user",
    db: Session = Depends(get_db),
):
    rule = db.query(MappingRule).filter(MappingRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    rule_data = {
        "rule_type": rule.rule_type,
        "source": rule.source_value,
        "target": rule.target_value,
    }

    deleted = feedback_svc.delete_rule(rule_id, db)
    if deleted:
        audit_svc.log_mapping_rule_deleted(rule_id=rule_id, actor=actor, rule_data=rule_data, db=db)
        return {"success": True, "rule_id": rule_id}
    else:
        raise HTTPException(status_code=404, detail="Rule not found")
