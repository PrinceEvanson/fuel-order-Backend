import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import require_role
from ..models import Document, User
from ..serializers import doc_to_dict
from ..services import audit, pipeline

router = APIRouter(prefix="/api/client", tags=["client"])
client_only = require_role("client")

ERROR_TYPES = {
    "wrong_customer", "wrong_po_number", "wrong_quantity_or_price", "missing_lines",
    "wrong_total", "wrong_product", "unreadable_scan", "wrong_document_section", "other",
}

def _own(db: Session, doc_id: int, user: User) -> Document:
    doc = db.get(Document, doc_id)
    if not doc or doc.owner_id != user.id:
        raise HTTPException(404, "Document not found")
    return doc

@router.post("/documents")
def upload(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(client_only)):
    raw = file.file.read()
    if not raw.startswith(b"%PDF"):
        raise HTTPException(400, "That file is not a PDF.")
    if len(raw) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"PDF is larger than {settings.MAX_UPLOAD_MB} MB.")
    doc = Document(owner_id=user.id, filename=(file.filename or "upload.pdf")[:500],
                   sha256=hashlib.sha256(raw).hexdigest(), pdf_bytes=raw, data={}, match={}, flags=[])
    db.add(doc)
    db.flush()
    pipeline.process(db, doc)
    audit.log(db, doc.id, "uploaded", user, {"filename": doc.filename, "ai_status": doc.ai_status})
    db.commit()
    return doc_to_dict(doc)

@router.get("/documents")
def list_mine(db: Session = Depends(get_db), user: User = Depends(client_only)):
    rows = db.scalars(select(Document).where(Document.owner_id == user.id, Document.status != "discarded")
                      .order_by(Document.created_at.desc())).all()
    return [doc_to_dict(d, full=False) for d in rows]

@router.get("/documents/{doc_id}")
def get_one(doc_id: int, db: Session = Depends(get_db), user: User = Depends(client_only)):
    return doc_to_dict(_own(db, doc_id, user))

class RedoIn(BaseModel):
    error_types: list[str]
    comment: str = ""

@router.post("/documents/{doc_id}/redo")
def redo(doc_id: int, body: RedoIn, db: Session = Depends(get_db), user: User = Depends(client_only)):
    doc = _own(db, doc_id, user)
    if doc.status != "extracted":
        raise HTTPException(409, "This document has already been sent and can no longer be redone.")
    types = [t for t in body.error_types if t in ERROR_TYPES]
    if not types and not body.comment.strip():
        raise HTTPException(422, "Tell us what went wrong (pick at least one issue or write a note).")
    report = {"error_types": types, "comment": body.comment.strip()[:1000],
              "at": datetime.now(timezone.utc).isoformat(), "attempt": doc.attempts}
    doc.feedback = [*(doc.feedback or []), report]
    hints = "; ".join(t.replace("_", " ") for t in types) + (f". Note: {report['comment']}" if report["comment"] else "")
    doc.attempts += 1
    pipeline.process(db, doc, hints=hints)
    audit.log(db, doc.id, "redo_requested", user, report)
    db.commit()
    return doc_to_dict(doc)

@router.post("/documents/{doc_id}/submit")
def submit(doc_id: int, db: Session = Depends(get_db), user: User = Depends(client_only)):
    doc = _own(db, doc_id, user)
    if doc.status != "extracted":
        raise HTTPException(409, f"Document is already {doc.status}.")
    pipeline.reanalyze(db, doc)
    if doc.ai_status == "failed":
        raise HTTPException(422, "The AI could not read this document. Redo the scan or upload a clearer PDF.")
    if any(f["code"] == "DUPLICATE" for f in doc.flags):
        db.commit()
        raise HTTPException(409, "This purchase order was already sent. Duplicates are not accepted.")
    doc.status = "submitted"
    doc.submitted_at = datetime.now(timezone.utc)
    audit.log(db, doc.id, "submitted", user, {"ai_status": doc.ai_status, "flags": [f["code"] for f in doc.flags]})
    db.commit()
    return doc_to_dict(doc)

@router.delete("/documents/{doc_id}")
def discard(doc_id: int, db: Session = Depends(get_db), user: User = Depends(client_only)):
    doc = _own(db, doc_id, user)
    if doc.status != "extracted":
        raise HTTPException(409, "Only documents that have not been sent can be discarded.")
    doc.status = "discarded"
    audit.log(db, doc.id, "discarded", user)
    db.commit()
    return {"ok": True}
