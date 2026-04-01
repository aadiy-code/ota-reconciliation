import os
import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import create_tables
from .config import settings
from .api.routes import health, files, reconciliation, review, mapping_rules

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting OTA Reconciliation System...")
    create_tables()
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    _seed_mapping_rules()
    logger.info("Startup complete.")
    yield
    # Shutdown
    logger.info("Shutting down...")


EMBEDDED_SEED_CONFIG = {
    "room_type_mappings": [
        {"source_value": "standard double room", "normalized": "standard_double", "platform": None},
        {"source_value": "standard twin room", "normalized": "standard_twin", "platform": None},
        {"source_value": "superior double room", "normalized": "superior_double", "platform": None},
        {"source_value": "deluxe double room", "normalized": "deluxe_double", "platform": None},
        {"source_value": "deluxe twin room", "normalized": "deluxe_twin", "platform": None},
        {"source_value": "executive room", "normalized": "executive", "platform": None},
        {"source_value": "junior suite", "normalized": "junior_suite", "platform": None},
        {"source_value": "suite", "normalized": "suite", "platform": None},
        {"source_value": "penthouse suite", "normalized": "penthouse", "platform": None},
        {"source_value": "studio", "normalized": "studio", "platform": None},
        {"source_value": "1 bedroom apartment", "normalized": "apartment_1br", "platform": None},
        {"source_value": "family room", "normalized": "family", "platform": None},
        {"source_value": "classic double", "normalized": "standard_double", "platform": "booking_com"},
        {"source_value": "comfort double", "normalized": "superior_double", "platform": "booking_com"},
        {"source_value": "premiere double", "normalized": "deluxe_double", "platform": "booking_com"},
        {"source_value": "standard room 1 king bed", "normalized": "standard_double", "platform": "expedia"},
        {"source_value": "deluxe room 1 king bed", "normalized": "deluxe_double", "platform": "expedia"},
        {"source_value": "standard room 2 twin beds", "normalized": "standard_twin", "platform": "expedia"},
        {"source_value": "std dbl", "normalized": "standard_double", "platform": "pms"},
        {"source_value": "dlx dbl", "normalized": "deluxe_double", "platform": "pms"},
        {"source_value": "sup dbl", "normalized": "superior_double", "platform": "pms"},
        {"source_value": "std twn", "normalized": "standard_twin", "platform": "pms"},
        {"source_value": "dlx twn", "normalized": "deluxe_twin", "platform": "pms"},
        {"source_value": "jr ste", "normalized": "junior_suite", "platform": "pms"},
        {"source_value": "fam rm", "normalized": "family", "platform": "pms"},
    ]
}


def _seed_mapping_rules():
    """Seed mapping rules from embedded config (works in all environments)."""
    try:
        config = EMBEDDED_SEED_CONFIG

        # Also try to load from file if available (local dev)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        candidate_paths = [
            os.path.normpath(os.path.join(base_dir, "..", "..", "..", "shared", "seed_config", "room_type_mapping.json")),
            os.path.normpath(os.path.join(base_dir, "..", "..", "shared", "seed_config", "room_type_mapping.json")),
        ]
        seed_path = next((p for p in candidate_paths if os.path.exists(p)), None)
        if seed_path:
            with open(seed_path, "r") as f:
                config = json.load(f)

        from .database import SessionLocal
        from .services.feedback_store import FeedbackStoreService

        db = SessionLocal()
        try:
            svc = FeedbackStoreService()
            count = svc.seed_from_config(config, db)
            logger.info(f"Seeded {count} mapping rules.")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Failed to seed mapping rules: {e}")


app = FastAPI(
    title="OTA Reconciliation System",
    description="Production-ready Online Travel Agency hotel reservation reconciliation system",
    version="1.0.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all routers
app.include_router(health.router)
app.include_router(files.router)
app.include_router(reconciliation.router)
app.include_router(review.router)
app.include_router(mapping_rules.router)


# Audit log endpoint
from fastapi import Depends
from sqlalchemy.orm import Session
from .database import get_db
from .models.db_models import AuditLog
from typing import Optional


@app.get("/api/v1/audit-logs", tags=["audit"])
def get_audit_logs(
    run_id: Optional[str] = None,
    actor: Optional[str] = None,
    action: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog)
    if run_id:
        query = query.filter(AuditLog.reconciliation_run_id == run_id)
    if actor:
        query = query.filter(AuditLog.actor == actor)
    if action:
        query = query.filter(AuditLog.action.contains(action))
    logs = query.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit).all()
    return [
        {
            "id": log.id,
            "reconciliation_run_id": log.reconciliation_run_id,
            "result_id": log.result_id,
            "action": log.action,
            "actor": log.actor,
            "before_state_json": log.before_state_json,
            "after_state_json": log.after_state_json,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


@app.get("/", tags=["root"])
def root():
    return {
        "message": "OTA Reconciliation System API",
        "version": "1.0.0",
        "docs": "/docs",
    }
