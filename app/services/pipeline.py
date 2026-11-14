import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Document
from . import checks, matcher
from .catalog import get_catalog
from .checks import flag, to_num
from .extractor import ExtractionError, extract_po

_LIVE = ("extracted", "submitted", "posting", "posted", "post_failed")

def _clean(data: dict) -> dict:
    data = dict(data or {})
    data["is_purchase_order"] = bool(data.get("is_purchase_order"))
    data["lines"] = [
        {"description": (ln.get("description") or "").strip(), "quantity": to_num(ln.get("quantity")),
         "unit": ln.get("unit"), "unit_price": to_num(ln.get("unit_price")), "line_total": to_num(ln.get("line_total"))}
        for ln in (data.get("lines") or [])
    ]
    data["document_total"] = to_num(data.get("document_total"))
    return data

def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

def _select(cands: list[dict], override_code: str | None):
    if override_code:
        for c in cands:
            if c["code"] == override_code:
                return {**c, "score": 1.0}, True
        return None, False
    if cands and cands[0]["score"] >= matcher.MIN_ACCEPT:
        return cands[0], False
    return None, False

def build_match(data: dict, catalog: dict, overrides: dict) -> dict:
    ccands = matcher.match_customer(data.get("customer_name") or "", data.get("delivery_address") or "", catalog["customers"], limit=5)
    csel, cmanual = _select(ccands, overrides.get("customer_code"))
    lines = []
    for i, ln in enumerate(data.get("lines") or []):
        pc = matcher.match_product(ln.get("description") or "", catalog["products"])
        psel, pmanual = _select(pc, (overrides.get("lines") or {}).get(str(i)))
        lines.append({"candidates": pc, "selected": psel, "manual": pmanual})
    return {"customer": {"candidates": ccands, "selected": csel, "manual": cmanual}, "lines": lines,
            "catalog_source": catalog["source"]}

def _fingerprint(data: dict, match: dict, sha: str) -> str:
    po = _key(data.get("po_number") or "")
    if not po:
        return f"sha:{sha}"
    sel = (match.get("customer") or {}).get("selected")
    who = sel["code"] if sel else _key(data.get("customer_name") or "")
    return f"{_key(who)}|{po}"

def reanalyze(db: Session, doc: Document) -> None:
    catalog = get_catalog(db)
    match = build_match(doc.data, catalog, doc.overrides or {})
    flags = checks.build_flags(doc.data, match)
    if catalog["error"]:
        flags.insert(0, flag("SAGE_CATALOG_ERROR", "error", f"Could not load customers/products from Sage: {catalog['error']}"))
    doc.match = match
    doc.fingerprint = _fingerprint(doc.data, match, doc.sha256)

    dup = db.scalars(select(Document).where(
        Document.id != doc.id, Document.status.in_(_LIVE),
        (Document.sha256 == doc.sha256) | (Document.fingerprint == doc.fingerprint),
    ).limit(1)).first()
    if dup:
        flags.insert(0, flag("DUPLICATE", "error",
                             f"Same document or same PO number already exists (document #{dup.id}, {dup.status}). "
                             "A second quote will not be created."))
    doc.flags = flags
    doc.ai_status = checks.ai_status_for(flags)

def process(db: Session, doc: Document, hints: str | None = None) -> None:
    try:
        doc.data = _clean(extract_po(doc.pdf_bytes, hints, doc.filename))
    except ExtractionError as e:
        doc.data = {"is_purchase_order": False, "lines": []}
        doc.match = {}
        doc.flags = [flag("EXTRACTION_FAILED", "error", str(e))]
        doc.ai_status = "failed"
        return
    doc.overrides = {}
    reanalyze(db, doc)
