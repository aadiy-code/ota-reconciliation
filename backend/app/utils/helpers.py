import uuid
import os
import json
from datetime import date, datetime
from typing import Any


def generate_uuid() -> str:
    return str(uuid.uuid4())


def safe_json_loads(value: Any, default=None):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def serialize_for_json(obj: Any) -> Any:
    """Recursively convert objects to JSON-serializable types."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: serialize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [serialize_for_json(i) for i in obj]
    return obj


def booking_to_dict(booking) -> dict:
    """Convert a NormalizedBooking DB model to a plain dict."""
    result = {}
    for col in booking.__table__.columns:
        val = getattr(booking, col.name)
        if isinstance(val, (date, datetime)):
            result[col.name] = val.isoformat()
        else:
            result[col.name] = val
    return result
