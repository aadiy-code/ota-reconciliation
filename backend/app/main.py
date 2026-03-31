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


def _seed_mapping_rules():
    """Seed mapping rules from the seed config file."""
    # Try multiple possible paths for the seed config
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidate_paths = [
        os.path.normpath(os.path.join(base_dir, "..", "..", "..", "shared", "seed_config", "room_type_mapping.json")),
        os.path.normpath(os.path.join(base_dir, "..", "..", "shared", "seed_config", "room_type_mapping.json")),
        os.path.normpath(os.path.join(os.getcwd(), "..", "shared", "seed_config", "room_type_mapping.json")),
        os.path.normpath(os.path.join(os.getcwd(), "shared", "seed_config", "room_type_mapping.json")),
    ]
    seed_path = next((p for p in candidate_paths if os.path.exists(p)), None)
    if not seed_path:
        logger.warning("Seed config not found in any candidate paths, skipping seed.")
        return

    try:
        with open(seed_path, "r") as f:
            config = json.load(f)

        from .database import SessionLocal
        from .services.feedback_store import FeedbackStoreService

        db = SessionLocal()
        try:
            svc = FeedbackStoreService()
            count = svc.seed_from_config(config, db)
            logger.info(f"Seeded {count} mapping rules from config.")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Failed to seed mapping rules: {e}")


app = FastAPI(
    title="OTA Reconciliation System",
    description="Production-ready Online Travel Agency hotel reservation reconciliation system",
    version="1.0.0",
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
