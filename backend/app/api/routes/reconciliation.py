import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.db_models import (
    ReconciliationRun, File as FileModel, RawRow,
    NormalizedBooking, ReconciliationResult
)
from ...schemas.canonical import (
    ReconciliationRunCreate, ReconciliationRunResponse,
    ReconciliationResultResponse, ExceptionFilters
)
from ...services.file_classifier import FileClassifierService
from ...services.schema_mapper import SchemaMapperService
from ...services.normalizer import BookingNormalizerService
from ...services.reconciliation_engine import ReconciliationService
from ...services.exception_queue import ExceptionQueueService
from ...services.report_generator import ReportGeneratorService
from ...services.audit_logger import AuditLoggerService
from ...utils.helpers import booking_to_dict

router = APIRouter(prefix="/api/v1/reconciliation", tags=["reconciliation"])

classifier = FileClassifierService()
schema_mapper = SchemaMapperService()
reconciliation_svc = ReconciliationService()
exception_svc = ExceptionQueueService()
report_svc = ReportGeneratorService()
audit_svc = AuditLoggerService()


def _process_file_to_normalized_bookings(
    file_record: FileModel,
    raw_rows: List[RawRow],
    run_id: str,
    db: Session,
) -> List[NormalizedBooking]:
    if not raw_rows:
        return []

    headers = list(raw_rows[0].raw_payload_json.keys())
    sample_rows = [r.raw_payload_json for r in raw_rows[:5]]

    mapping_result = schema_mapper.map_columns(
        headers=headers,
        sample_rows=sample_rows,
        source_platform=file_record.source_platform,
        db=db,
    )

    normalizer = BookingNormalizerService(db=db)
    bookings = []

    for raw_row in raw_rows:
        try:
            canonical = normalizer.normalize_booking(
                raw_row=raw_row.raw_payload_json,
                column_mapping=mapping_result.column_mapping,
                source_platform=file_record.source_platform,
                source_file_name=file_record.file_name,
                source_row_number=raw_row.source_row_number,
                reconciliation_run_id=run_id,
                file_id=file_record.id,
            )
            db_booking = NormalizedBooking(
                id=canonical.id,
                reconciliation_run_id=run_id,
                file_id=file_record.id,
                source_platform=canonical.source_platform.value,
                hotel_id=canonical.hotel_id,
                external_reservation_id=canonical.external_reservation_id,
                pms_reservation_id=canonical.pms_reservation_id,
                channel_reference_id=canonical.channel_reference_id,
                booking_status=canonical.booking_status.value,
                guest_name_raw=canonical.guest_name_raw,
                guest_name_normalized=canonical.guest_name_normalized,
                check_in_date=canonical.check_in_date,
                check_out_date=canonical.check_out_date,
                number_of_nights=canonical.number_of_nights,
                booking_date=canonical.booking_date,
                room_type_raw=canonical.room_type_raw,
                room_type_normalized=canonical.room_type_normalized,
                guest_count=canonical.guest_count,
                adults=canonical.adults,
                children=canonical.children,
                currency=canonical.currency,
                gross_amount=canonical.gross_amount,
                net_amount=canonical.net_amount,
                taxes_and_fees=canonical.taxes_and_fees,
                commission_amount=canonical.commission_amount,
                payment_type=canonical.payment_type.value,
                source_file_name=canonical.source_file_name,
                source_row_number=canonical.source_row_number,
                raw_payload_json=canonical.raw_payload_json,
            )
            db.add(db_booking)
            bookings.append(canonical)
        except Exception:
            continue

    db.commit()
    return bookings


def _run_reconciliation_task(run_id: str, file_ids: List[str], hotel_id: Optional[str], db: Session):
    run = db.query(ReconciliationRun).filter(ReconciliationRun.id == run_id).first()
    if not run:
        return

    try:
        run.status = "running"
        db.commit()

        ota_bookings = []
        pms_bookings = []

        for file_id in file_ids:
            file_record = db.query(FileModel).filter(FileModel.id == file_id).first()
            if not file_record:
                continue

            # Link file to run
            file_record.reconciliation_run_id = run_id
            db.commit()

            raw_rows = db.query(RawRow).filter(RawRow.file_id == file_id).all()
            normalized = _process_file_to_normalized_bookings(file_record, raw_rows, run_id, db)

            if file_record.source_platform in ("booking_com", "expedia"):
                ota_bookings.extend(normalized)
            elif file_record.source_platform == "pms":
                pms_bookings.extend(normalized)
            else:
                # Unknown - try to classify by content
                ota_bookings.extend(normalized)

        # Run reconciliation
        summary = reconciliation_svc.run_reconciliation(run_id, ota_bookings, pms_bookings, db)
        audit_svc.log_run_completed(run_id, summary.to_dict(), db)

    except Exception as e:
        run.status = "failed"
        run.run_completed_at = datetime.utcnow()
        db.commit()
        raise


@router.post("/start", response_model=ReconciliationRunResponse)
def start_reconciliation(
    body: ReconciliationRunCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    run_id = str(uuid.uuid4())
    run = ReconciliationRun(
        id=run_id,
        hotel_id=body.hotel_id,
        triggered_by=body.triggered_by,
        status="pending",
        run_started_at=datetime.utcnow(),
    )
    db.add(run)
    db.commit()

    audit_svc.log_run_started(run_id, body.triggered_by, db)

    # Run synchronously for simplicity (can be moved to background with a task queue)
    # Using background task for non-blocking response
    from ...database import SessionLocal
    def run_task():
        task_db = SessionLocal()
        try:
            _run_reconciliation_task(run_id, body.file_ids, body.hotel_id, task_db)
        finally:
            task_db.close()

    background_tasks.add_task(run_task)

    db.refresh(run)
    return ReconciliationRunResponse(
        id=run.id,
        hotel_id=run.hotel_id,
        run_started_at=run.run_started_at,
        run_completed_at=run.run_completed_at,
        triggered_by=run.triggered_by,
        status=run.status,
        summary_json=run.summary_json,
        created_at=run.created_at,
    )


@router.get("/runs", response_model=List[ReconciliationRunResponse])
def list_runs(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    runs = db.query(ReconciliationRun).order_by(
        ReconciliationRun.created_at.desc()
    ).offset(skip).limit(limit).all()
    return [
        ReconciliationRunResponse(
            id=r.id,
            hotel_id=r.hotel_id,
            run_started_at=r.run_started_at,
            run_completed_at=r.run_completed_at,
            triggered_by=r.triggered_by,
            status=r.status,
            summary_json=r.summary_json,
            created_at=r.created_at,
        )
        for r in runs
    ]


@router.get("/runs/{run_id}", response_model=ReconciliationRunResponse)
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(ReconciliationRun).filter(ReconciliationRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return ReconciliationRunResponse(
        id=run.id,
        hotel_id=run.hotel_id,
        run_started_at=run.run_started_at,
        run_completed_at=run.run_completed_at,
        triggered_by=run.triggered_by,
        status=run.status,
        summary_json=run.summary_json,
        created_at=run.created_at,
    )


@router.get("/runs/{run_id}/summary")
def get_run_summary(run_id: str, db: Session = Depends(get_db)):
    run = db.query(ReconciliationRun).filter(ReconciliationRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "run_id": run_id,
        "status": run.status,
        "summary": run.summary_json or {},
    }


@router.get("/runs/{run_id}/results")
def get_run_results(
    run_id: str,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(ReconciliationResult).filter(
        ReconciliationResult.reconciliation_run_id == run_id
    )
    if status:
        query = query.filter(ReconciliationResult.reconciliation_status == status)

    total = query.count()
    results = query.offset(skip).limit(limit).all()

    rows = []
    for r in results:
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
            "reconciliation_run_id": r.reconciliation_run_id,
            "ota_booking_id": r.ota_booking_id,
            "pms_booking_id": r.pms_booking_id,
            "reconciliation_status": r.reconciliation_status,
            "confidence_score": r.confidence_score,
            "matched_rule": r.matched_rule,
            "reason_codes": r.reason_codes_json,
            "explanation_text": r.explanation_text,
            "review_decision": r.review_decision,
            "reviewed_by": r.reviewed_by,
            "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
            "review_notes": r.review_notes,
            "is_manual_override": r.is_manual_override,
            "ota_booking": ota,
            "pms_booking": pms,
        })

    return {"total": total, "results": rows}


@router.get("/runs/{run_id}/exceptions")
def get_exceptions(
    run_id: str,
    status: Optional[str] = None,
    min_confidence: Optional[float] = None,
    max_confidence: Optional[float] = None,
    reason_code: Optional[str] = None,
    db: Session = Depends(get_db),
):
    filters = ExceptionFilters(
        status=status,
        min_confidence=min_confidence,
        max_confidence=max_confidence,
        reason_code=reason_code,
    )
    exceptions = exception_svc.get_exceptions(run_id, db, filters)

    rows = []
    for r in exceptions:
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
            "is_manual_override": r.is_manual_override,
            "ota_booking": ota,
            "pms_booking": pms,
        })

    return {"total": len(rows), "exceptions": rows}


@router.get("/runs/{run_id}/export")
def export_run(
    run_id: str,
    format: str = Query("csv", pattern="^(csv|xlsx)$"),
    exceptions_only: bool = False,
    db: Session = Depends(get_db),
):
    run = db.query(ReconciliationRun).filter(ReconciliationRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    if format == "csv":
        content = report_svc.export_to_csv(run_id, db, exceptions_only)
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=reconciliation_{run_id[:8]}.csv"},
        )
    else:
        content = report_svc.export_to_xlsx(run_id, db)
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=reconciliation_{run_id[:8]}.xlsx"},
        )
