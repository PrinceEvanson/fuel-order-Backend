from .models import Document

def _iso(d):
    return d.isoformat() if d else None

def doc_to_dict(doc: Document, full: bool = True) -> dict:
    d = {
        "id": doc.id,
        "filename": doc.filename,
        "status": doc.status,
        "ai_status": doc.ai_status,
        "attempts": doc.attempts,
        "owner": doc.owner.name if doc.owner else None,
        "customer_name": (doc.data or {}).get("customer_name"),
        "po_number": (doc.data or {}).get("po_number"),
        "flag_count": len([f for f in (doc.flags or []) if f["severity"] in ("error", "warn")]),
        "created_at": _iso(doc.created_at),
        "submitted_at": _iso(doc.submitted_at),
        "posted_at": _iso(doc.posted_at),
        "reject_reason": doc.reject_reason,
        "sage_quote_number": doc.sage_quote_number,
        "sage_url": doc.sage_url,
    }
    if full:
        d.update({
            "data": doc.data, "match": doc.match, "flags": doc.flags, "feedback": doc.feedback,
            "sage_error": doc.sage_error,
            "reviewed_by": doc.reviewer.name if doc.reviewer else None,
            "reviewed_at": _iso(doc.reviewed_at),
        })
    return d
