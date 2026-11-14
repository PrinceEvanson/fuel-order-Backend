from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Document, User

router = APIRouter(prefix="/api/documents", tags=["files"])

@router.get("/{doc_id}/file")
def download(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = db.get(Document, doc_id)
    if not doc or (user.role != "reviewer" and doc.owner_id != user.id):
        raise HTTPException(404, "Document not found")
    safe = doc.filename.encode("ascii", "ignore").decode().replace('"', "") or "document.pdf"
    return Response(doc.pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{safe}"'})
