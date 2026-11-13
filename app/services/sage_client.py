from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import SageToken, utcnow

AUTH_URL = "https://www.sageone.com/oauth2/auth/central"
TOKEN_URL = "https://oauth.accounting.sage.com/token"
API = "https://api.accounting.sage.com/v3.1"


class SageError(Exception):
    pass


def authorize_url(state: str) -> str:
    if not settings.SAGE_CLIENT_ID:
        raise SageError("SAGE_CLIENT_ID is not configured.")
    q = {"filter": "apiv3.1", "response_type": "code", "client_id": settings.SAGE_CLIENT_ID,
         "redirect_uri": settings.SAGE_REDIRECT_URI, "scope": "full_access", "state": state}
    return f"{AUTH_URL}?{urlencode(q)}"


def _token_request(form: dict) -> dict:
    form = {**form, "client_id": settings.SAGE_CLIENT_ID,
            "client_secret": settings.SAGE_CLIENT_SECRET}
    try:
        r = httpx.post(TOKEN_URL, data=form, timeout=30)
    except httpx.HTTPError as e:
        raise SageError(f"Could not reach Sage to sign in: {e}")
    if r.status_code != 200:
        raise SageError(
            f"Sage refused the sign-in ({r.status_code}): {r.text[:300]}")
    return r.json()


def _store(db: Session, tok: dict, connected_by: str | None = None) -> SageToken:
    row = db.get(SageToken, 1) or SageToken(
        id=1, connected_by=connected_by or "")
    row.access_token = tok["access_token"]
    row.refresh_token = tok["refresh_token"]
    row.expires_at = datetime.now(
        timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 300)))
    row.updated_at = utcnow()
    if connected_by:
        row.connected_by = connected_by
    db.add(row)
    db.commit()
    return row


def exchange_code(db: Session, code: str, connected_by: str) -> None:
    tok = _token_request({"grant_type": "authorization_code", "code": code,
                          "redirect_uri": settings.SAGE_REDIRECT_URI})
    _store(db, tok, connected_by)


def is_connected(db: Session) -> bool:
    return db.get(SageToken, 1) is not None


def _fresh_token(db: Session, force: bool = False) -> str:
    row = db.get(SageToken, 1)
    if not row:
        raise SageError(
            "Sage is not connected. A reviewer must connect it first.")
    exp = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(
        tzinfo=timezone.utc)
    if force or exp - timedelta(seconds=60) <= datetime.now(timezone.utc):
        try:
            tok = _token_request(
                {"grant_type": "refresh_token", "refresh_token": row.refresh_token})
        except SageError as e:
            raise SageError(
                f"Sage session expired and could not be refreshed - reconnect Sage. ({e})")
        row = _store(db, tok)
    return row.access_token


def _format_errors(r: httpx.Response) -> str:
    try:
        body = r.json()
        if isinstance(body, list):
            return "; ".join(f"{e.get('$message', e)}" + (f" [{e.get('$source')}]" if e.get("$source") else "") for e in body)
        return str(body)[:500]
    except Exception:
        return r.text[:500]


def _request(db: Session, method: str, url: str, **kw) -> dict:
    full = url if url.startswith("http") else f"{API}{url}"
    for attempt in (0, 1):
        headers = {
            "Authorization": f"Bearer {_fresh_token(db, force=attempt == 1)}", "Content-Type": "application/json"}
        try:
            r = httpx.request(method, full, headers=headers, timeout=45, **kw)
        except httpx.HTTPError as e:
            raise SageError(f"Could not reach Sage: {e}")
        if r.status_code == 401 and attempt == 0:
            continue
        if r.status_code >= 400:
            raise SageError(
                f"Sage rejected the request ({r.status_code}): {_format_errors(r)}")
        return r.json()
    raise SageError("Sage rejected our credentials - reconnect Sage.")


def _list_all(db: Session, path: str, params: dict | None = None, max_pages: int = 10) -> list[dict]:
    out, url, p = [], path, {"items_per_page": 200, **(params or {})}
    for _ in range(max_pages):
        body = _request(db, "GET", url, params=p)
        out.extend(body.get("$items", []))
        nxt = body.get("$next")
        if not nxt:
            break
        url, p = nxt, None
    return out


def list_customers(db: Session) -> list[dict]:
    return _list_all(db, "/contacts", {"contact_type_id": "CUSTOMER"})


def list_products(db: Session) -> list[dict]:
    return _list_all(db, "/products")


def _sales_ledger_id(db: Session) -> str:
    if settings.SAGE_SALES_LEDGER_ACCOUNT_ID:
        return settings.SAGE_SALES_LEDGER_ACCOUNT_ID
    accts = _list_all(db, "/ledger_accounts", {"visible_in": "sales"})
    if not accts:
        raise SageError(
            "No sales ledger account found in Sage. Set SAGE_SALES_LEDGER_ACCOUNT_ID.")
    preferred = [a for a in accts if "sales" in (
        a.get("displayed_as") or "").lower()]
    return (preferred or accts)[0]["id"]


def _zero_tax_rate_id(db: Session) -> str:
    if settings.SAGE_TAX_RATE_ID:
        return settings.SAGE_TAX_RATE_ID
    for t in _list_all(db, "/tax_rates"):
        try:
            if float(t.get("percentage", 1)) == 0:
                return t["id"]
        except (TypeError, ValueError):
            continue
    raise SageError(
        "No zero-rate tax rate found in Sage. Set SAGE_TAX_RATE_ID.")


def create_sales_quote(db: Session, *, contact_id: str, lines: list[dict], po_number: str | None,
                       currency: str | None, notes: str) -> dict:
    ledger, tax = _sales_ledger_id(db), _zero_tax_rate_id(db)
    today = datetime.now(timezone.utc).date()
    payload = {"sales_quote": {
        "contact_id": contact_id,
        "date": today.isoformat(),
        "expiry_date": (today + timedelta(days=14)).isoformat(),
        "reference": (po_number or "")[:50],
        "notes": notes + (f"\nDocument currency: {currency}" if currency else ""),
        "quote_lines": [{
            "product_id": ln["product_id"],
            "description": ln["description"],
            "quantity": ln["quantity"],
            "unit_price": ln["unit_price"],
            "ledger_account_id": ledger,
            "tax_rate_id": tax,
        } for ln in lines],
    }}
    body = _request(db, "POST", "/sales_quotes", json=payload)
    qid = body.get("id")
    return {"id": qid, "number": body.get("quote_number") or body.get("displayed_as") or qid,
            "url": settings.SAGE_WEB_QUOTE_URL.format(id=qid)}
