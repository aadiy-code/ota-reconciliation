from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.db_models import ReconciliationResult, NormalizedBooking
from ...schemas.canonical import ReviewDecisionRequest
from ...services.exception_queue import ExceptionQueueService
from ...utils.helpers import booking_to_dict

router = APIRouter(prefix="/api/v1/review", tags=["review"])

exception_svc = ExceptionQueueService()

EXCEPTION_STATUSES = {
    "missing_in_pms", "missing_in_ota", "duplicate_in_pms",
    "duplicate_in_ota", "cancellation_mismatch", "modification_mismatch",
    "amount_mismatch", "pending_review",
}


@router.get("/{run_id}/queue")
def get_review_queue(run_id: str, db: Session = Depends(get_db)):
    items = exception_svc.get_pending_review(run_id, db)
    rows = []
    for r in items:
        ota = None
        pms = None
        if r.ota_booking_id:
            ota_db = db.query(NormalizedBooking).filter(NormalizedBooking.id == r.ota_booking_id).first()
            if ota_db:
                ota = booking_to_dict(ota_db)
        if r.pms_booking_id:
            pms_db = db.query(NormalizedBooking).filter(NormalizedBooking.id == r.pms_booking_id).first()
            if pms_db:
                pms = booking_to_dict(pms_db)

        rows.append({
            "id": r.id,
            "reconciliation_status": r.reconciliation_status,
            "confidence_score": r.confidence_score,
            "matched_rule": r.matched_rule,
            "reason_codes": r.reason_codes_json,
            "explanation_text": r.explanation_text,
            "review_decision": r.review_decision,
            "ota_booking": ota,
            "pms_booking": pms,
        })

    return {"total": len(rows), "items": rows}


@router.post("/{result_id}")
def submit_review_decision(
    result_id: str,
    body: ReviewDecisionRequest,
    db: Session = Depends(get_db),
):
    if body.decision not in ("accepted", "rejected", "marked_variance"):
        raise HTTPException(
            status_code=400,
            detail="decision must be one of: accepted, rejected, marked_variance",
        )

    result = db.query(ReconciliationResult).filter(
        ReconciliationResult.id == result_id
    ).first()
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    updated = exception_svc.apply_review_decision(result_id, body, db)

    return {
        "success": True,
        "result_id": result_id,
        "new_status": updated.reconciliation_status,
        "review_decision": updated.review_decision,
        "reviewed_by": updated.reviewed_by,
    }
