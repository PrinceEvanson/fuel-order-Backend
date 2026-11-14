from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import require_role
from ..models import AuditLog, Document, User
from ..serializers import doc_to_dict
from ..services import audit, pipeline, sage_client
from ..services.checks import blocking, to_num

router = APIRouter(prefix="/api/review", tags=["review"])
reviewer_only = require_role("reviewer")

VISIBLE = ("submitted", "posting", "posted", "post_failed", "rejected")

def _get(db: Session, doc_id: int) -> Document:
    doc = db.get(Document, doc_id)
    if not doc or doc.status not in VISIBLE:
        raise HTTPException(404, "Document not found")
    return doc

@router.get("/documents")
def queue(bucket: str = "pending", db: Session = Depends(get_db), _: User = Depends(reviewer_only)):
    q = select(Document).where(Document.status.in_(VISIBLE)).order_by(Document.submitted_at.desc())
    rows = db.scalars(q).all()
    pending = [d for d in rows if d.status in ("submitted", "post_failed", "posting")]
    pick = {
        "pending": pending,
        "passed": [d for d in pending if d.ai_status == "passed"],
        "flagged": [d for d in pending if d.ai_status != "passed"],
        "posted": [d for d in rows if d.status == "posted"],
        "rejected": [d for d in rows if d.status == "rejected"],
    }.get(bucket)
    if pick is None:
        raise HTTPException(400, "Unknown bucket")
    return {"items": [doc_to_dict(d, full=False) for d in pick],
            "counts": {k: len(v) for k, v in pick_all(pending, rows).items()}}

def pick_all(pending, rows):
    return {"pending": pending, "passed": [d for d in pending if d.ai_status == "passed"],
            "flagged": [d for d in pending if d.ai_status != "passed"],
            "posted": [d for d in rows if d.status == "posted"], "rejected": [d for d in rows if d.status == "rejected"]}

@router.get("/stats")
def stats(db: Session = Depends(get_db), _: User = Depends(reviewer_only)):
    rows = db.scalars(select(Document).where(Document.status.in_(VISIBLE))).all()
    today = datetime.now(timezone.utc).date()

    def aware(d):
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

    posted = [d for d in rows if d.status == "posted" and d.posted_at]
    secs = [(aware(d.posted_at) - aware(d.created_at)).total_seconds() for d in posted]
    return {
        "waiting": len([d for d in rows if d.status in ("submitted", "post_failed")]),
        "approved_today": len([d for d in posted if aware(d.posted_at).date() == today]),
        "avg_upload_to_pfi_minutes": round(sum(secs) / len(secs) / 60, 1) if secs else None,
    }

@router.get("/documents/{doc_id}")
def detail(doc_id: int, db: Session = Depends(get_db), _: User = Depends(reviewer_only)):
    return doc_to_dict(_get(db, doc_id))

@router.get("/documents/{doc_id}/audit")
def audit_trail(doc_id: int, db: Session = Depends(get_db), _: User = Depends(reviewer_only)):
    _get(db, doc_id)
    rows = db.scalars(select(AuditLog).where(AuditLog.document_id == doc_id).order_by(AuditLog.created_at)).all()
    return [{"id": r.id, "actor": r.actor_name, "action": r.action, "detail": r.detail,
             "at": r.created_at.isoformat()} for r in rows]

class LineIn(BaseModel):
    description: str = ""
    quantity: float | None = None
    unit: str | None = None
    unit_price: float | None = None
    line_total: float | None = None

class EditIn(BaseModel):
    customer_name: str | None = None
    po_number: str | None = None
    po_date: str | None = None
    delivery_address: str | None = None
    currency: str | None = None
    document_total: float | None = None
    lines: list[LineIn]
    customer_code: str | None = None
    product_codes: dict[str, str] = {}

@router.put("/documents/{doc_id}/fields")
def edit_fields(doc_id: int, body: EditIn, db: Session = Depends(get_db), user: User = Depends(reviewer_only)):
    doc = _get(db, doc_id)
    if doc.status not in ("submitted", "post_failed"):
        raise HTTPException(409, f"Document is {doc.status} and can no longer be edited.")
    before = dict(doc.data)
    new = {**doc.data, **body.model_dump(exclude={"lines", "customer_code", "product_codes"}),
           "lines": [ln.model_dump() for ln in body.lines]}
    new["is_purchase_order"] = doc.data.get("is_purchase_order", False)
    doc.data = new
    doc.overrides = {"customer_code": body.customer_code or None,
                     "lines": {k: v for k, v in body.product_codes.items() if v}}
    pipeline.reanalyze(db, doc)
    changed = sorted(k for k in new if new.get(k) != before.get(k))
    audit.log(db, doc.id, "edited", user, {"changed": changed, "overrides": doc.overrides})
    db.commit()
    return doc_to_dict(doc)

class RejectIn(BaseModel):
    reason: str

@router.post("/documents/{doc_id}/reject")
def reject(doc_id: int, body: RejectIn, db: Session = Depends(get_db), user: User = Depends(reviewer_only)):
    reason = body.reason.strip()
    if len(reason) < 3:
        raise HTTPException(422, "A reason for rejecting is required.")
    doc = _get(db, doc_id)
    if doc.status not in ("submitted", "post_failed"):
        raise HTTPException(409, f"Document is already {doc.status}.")
    doc.status, doc.reject_reason = "rejected", reason
    doc.reviewed_by_id, doc.reviewed_at = user.id, datetime.now(timezone.utc)
    audit.log(db, doc.id, "rejected", user, {"reason": reason})
    db.commit()
    return doc_to_dict(doc)

class ApproveIn(BaseModel):
    acknowledge_warnings: bool = False

@router.post("/documents/{doc_id}/approve")
def approve(doc_id: int, body: ApproveIn, db: Session = Depends(get_db), user: User = Depends(reviewer_only)):
    doc = _get(db, doc_id)
    if doc.status not in ("submitted", "post_failed"):
        raise HTTPException(409, f"Document is already {doc.status}.")

    pipeline.reanalyze(db, doc)
    errors = blocking(doc.flags)
    if errors:
        db.commit()
        raise HTTPException(422, {"message": "Fix these before posting to Sage.", "blockers": errors})
    warns = [f for f in doc.flags if f["severity"] == "warn"]
    if warns and not body.acknowledge_warnings:
        raise HTTPException(422, {"message": "Confirm you have reviewed the warnings.", "blockers": warns})

    cust = doc.match["customer"]["selected"]
    lines = []
    for ln, lm in zip(doc.data["lines"], doc.match["lines"]):
        p = lm["selected"]
        lines.append({"product_id": p["sage_id"], "description": ln["description"] or p["description"],
                      "quantity": to_num(ln["quantity"]), "unit_price": to_num(ln["unit_price"])})
    mock_sage = settings.MOCK_SAGE and not sage_client.is_connected(db)
    if not mock_sage and (not cust.get("sage_id") or any(not ln["product_id"] for ln in lines)):
        raise HTTPException(422, {"message": "Customer/products are not linked to Sage records. Connect Sage first.",
                                  "blockers": []})

    doc.status, doc.posted_fingerprint, doc.posted_sha256 = "posting", doc.fingerprint, doc.sha256
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A quote for this purchase order already exists. Duplicate blocked.")

    notes = (f"Created from file '{doc.filename}' (doc #{doc.id}, sha256 {doc.sha256[:12]}). "
             f"Approved by {user.name} at {datetime.now(timezone.utc).isoformat(timespec='seconds')}.")
    try:
        if mock_sage:
            quote = {"id": f"demo-{doc.id}", "number": f"DEMO-{doc.id:05d}", "url": None}
        else:
            quote = sage_client.create_sales_quote(db, contact_id=cust["sage_id"], lines=lines,
                                                   po_number=doc.data.get("po_number"),
                                                   currency=doc.data.get("currency"), notes=notes)
    except sage_client.SageError as e:
        doc.status, doc.posted_fingerprint, doc.posted_sha256, doc.sage_error = "post_failed", None, None, str(e)
        audit.log(db, doc.id, "post_failed", user, {"error": str(e)})
        db.commit()
        raise HTTPException(502, str(e))

    now = datetime.now(timezone.utc)
    doc.status, doc.sage_error = "posted", None
    doc.sage_quote_id, doc.sage_quote_number, doc.sage_url = quote["id"], str(quote["number"]), quote["url"]
    doc.reviewed_by_id, doc.reviewed_at, doc.posted_at = user.id, now, now
    audit.log(db, doc.id, "approved_and_posted", user, {"sage_quote_id": quote["id"], "sage_quote_number": str(quote["number"]),
                                                        "warnings_acknowledged": [w["code"] for w in warns]})
    db.commit()
    return doc_to_dict(doc)
