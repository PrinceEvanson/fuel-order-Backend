import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select

from .db import Base, SessionLocal, engine
from .models import Document, User
from .services import audit, pipeline

DEMO_DIR = Path(__file__).resolve().parent.parent / "demo_pdfs"

SOURCES = [
    {
        "file": "sandiego-po-4500101461.pdf",
        "url": "https://apps.sandiego.gov/directories/purchasing/pdf/pos/2019/4500101461.pdf",
    },
    {
        "file": "garland-isd-fuel-rfp-addendum-1.pdf",
        "url": "https://garlandisd.net/sites/default/files/2025-07/addendum_1_-_to_post_1.pdf",
    },
    {
        "file": "mbeya-zonal-referral-hospital-contract-34.pdf",
        "url": "https://www.mof.go.tz/uploads/text-editor/files/MZRH%20CONTRACT%20NO%2034_1658571884.pdf",
    },
    {
        "file": "kisumu-county-fuel-tender.pdf",
        "url": "https://www.kisumu.go.ke/wp-content/uploads/SUPPLY-AND-DELIVERY-OF-PETROL-DIESEL-OIL-LUBRICANT-AND-GAS.pdf",
    },
    {
        "file": "bomet-county-fuel-framework-bid.pdf",
        "url": "https://bomet.go.ke/wp-content/uploads/2026/06/12.-Framework-Bid-Document-for-SUPPLY-DELIVERY-OF-FUELOIL-AND-LUBS.pdf",
    },
    {
        "file": "diesel-invoice-money-receipt.pdf",
        "url": None,
        "page": "https://www.scribd.com/document/335005694/Diesel-Invoice",
    },
    {
        "file": "proforma-invoice-diesel-rccl.pdf",
        "url": None,
        "page": "https://www.scribd.com/document/386354006/Proforma-Invoice-Diesel-RCCL",
    },
]

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}


def fetch(src: dict) -> Path | None:
    path = DEMO_DIR / src["file"]
    if path.exists() and path.read_bytes()[:4] == b"%PDF":
        return path
    if not src["url"]:
        print(f"manual: download {src['page']} and save it as demo_pdfs/{src['file']}")
        return None
    try:
        r = httpx.get(src["url"], headers=HEADERS, follow_redirects=True, timeout=90)
    except httpx.HTTPError as e:
        print(f"failed: {src['file']} ({e})")
        return None
    if r.status_code != 200 or not r.content.startswith(b"%PDF"):
        print(f"failed: {src['file']} (status {r.status_code}, not a PDF). Save it by hand as demo_pdfs/{src['file']}")
        return None
    path.write_bytes(r.content)
    print(f"downloaded: {src['file']} ({len(r.content) // 1024} KB)")
    return path


def main() -> None:
    Base.metadata.create_all(engine)
    DEMO_DIR.mkdir(exist_ok=True)
    email = os.environ.get("SEED_CLIENT_EMAIL", "client@demo.com").lower()
    with SessionLocal() as db:
        owner = db.scalars(select(User).where(User.email == email)).first()
        if not owner:
            sys.exit("Demo client account not found. Run: python -m app.seed")
        added = 0
        for src in SOURCES:
            path = fetch(src)
            if not path:
                continue
            raw = path.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            if db.scalars(select(Document).where(Document.sha256 == sha)).first():
                print(f"already loaded: {src['file']}")
                continue
            doc = Document(owner_id=owner.id, filename=src["file"], sha256=sha, pdf_bytes=raw,
                           data={}, match={}, flags=[])
            db.add(doc)
            db.flush()
            pipeline.process(db, doc)
            doc.status = "submitted"
            doc.submitted_at = datetime.now(timezone.utc)
            audit.log(db, doc.id, "uploaded", owner, {"filename": doc.filename, "ai_status": doc.ai_status, "demo": True})
            audit.log(db, doc.id, "submitted", owner, {"ai_status": doc.ai_status, "demo": True})
            db.commit()
            added += 1
            print(f"loaded: {src['file']} ({doc.ai_status})")
        print(f"done. {added} demo document(s) added to the reviewer queue.")


if __name__ == "__main__":
    main()
