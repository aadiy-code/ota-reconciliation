import os
import shutil
import uuid
from typing import List
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Form
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.db_models import File as FileModel, RawRow
from ...schemas.canonical import FileUploadResponse
from ...services.file_classifier import FileClassifierService
from ...services.schema_mapper import SchemaMapperService
from ...config import settings
from ...utils.helpers import ensure_dir

import pandas as pd

router = APIRouter(prefix="/api/v1/files", tags=["files"])

classifier = FileClassifierService()
schema_mapper = SchemaMapperService()


def read_file_as_df(file_path: str, file_type: str) -> pd.DataFrame:
    if file_type == "csv":
        return pd.read_csv(
            file_path, dtype=str, keep_default_na=False,
            index_col=False, on_bad_lines="warn", encoding_errors="replace",
        )
    elif file_type in ("xlsx", "xls"):
        return pd.read_excel(file_path, dtype=str, keep_default_na=False)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")


@router.post("/upload", response_model=List[FileUploadResponse])
async def upload_files(
    files: List[UploadFile] = File(...),
    run_id: str = Form(None),
    db: Session = Depends(get_db),
):
    ensure_dir(settings.UPLOAD_DIR)
    results = []

    for upload in files:
        filename = upload.filename or "unknown_file"
        file_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "csv"
        if file_ext not in ("csv", "xlsx", "xls"):
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_ext}")

        file_id = str(uuid.uuid4())
        safe_name = f"{file_id}_{filename}"
        file_path = os.path.join(settings.UPLOAD_DIR, safe_name)

        with open(file_path, "wb") as f:
            shutil.copyfileobj(upload.file, f)

        # Parse file
        try:
            df = read_file_as_df(file_path, file_ext)
            headers = list(df.columns)
            sample_rows = df.head(5).to_dict(orient="records")
            row_count = len(df)
            parse_status = "success"
        except Exception as e:
            headers = []
            sample_rows = []
            row_count = 0
            parse_status = "failed"

        # Classify
        classification = classifier.classify(headers, sample_rows)

        # Create DB record
        file_record = FileModel(
            id=file_id,
            reconciliation_run_id=run_id,
            file_name=filename,
            source_platform=classification.source_platform.value,
            file_type=file_ext,
            parse_status=parse_status,
            row_count=row_count,
            file_path=file_path,
            classifier_confidence=classification.confidence,
        )
        db.add(file_record)

        # Store raw rows
        if parse_status == "success":
            for i, row in enumerate(df.to_dict(orient="records"), start=1):
                raw_row = RawRow(
                    file_id=file_id,
                    source_row_number=i,
                    raw_payload_json=row,
                )
                db.add(raw_row)

        db.commit()

        results.append(FileUploadResponse(
            file_id=file_id,
            file_name=filename,
            source_platform=classification.source_platform.value,
            classifier_confidence=classification.confidence,
            row_count=row_count,
            parse_status=parse_status,
        ))

    return results


@router.get("/{file_id}")
def get_file(file_id: str, db: Session = Depends(get_db)):
    file_record = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    return {
        "id": file_record.id,
        "file_name": file_record.file_name,
        "source_platform": file_record.source_platform,
        "file_type": file_record.file_type,
        "uploaded_at": file_record.uploaded_at.isoformat() if file_record.uploaded_at else None,
        "parse_status": file_record.parse_status,
        "row_count": file_record.row_count,
        "classifier_confidence": file_record.classifier_confidence,
        "reconciliation_run_id": file_record.reconciliation_run_id,
    }
