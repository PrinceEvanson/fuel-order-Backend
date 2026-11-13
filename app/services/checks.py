from .matcher import AUTO_ACCEPT, MIN_ACCEPT

TOL = 0.01


def to_num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def flag(code: str, severity: str, message: str, field: str | None = None) -> dict:
    return {"code": code, "severity": severity, "message": message, "field": field}


def check_math(data: dict) -> list[dict]:
    flags = []
    line_sum, all_totals = 0.0, True
    for i, ln in enumerate(data.get("lines") or []):
        q, p, t = to_num(ln.get("quantity")), to_num(
            ln.get("unit_price")), to_num(ln.get("line_total"))
        label = f"Line {i + 1}"
        if t is None:
            all_totals = False
        else:
            line_sum += t
        if q is not None and p is not None and t is not None and abs(q * p - t) > TOL:
            flags.append(flag(
                "LINE_TOTAL_MISMATCH", "warn",
                f"{label}: quantity {q:g} x unit price {p:g} = {q * p:,.2f}, but the document says {t:,.2f}",
                f"lines.{i}.line_total",
            ))
    doc_total = to_num(data.get("document_total"))
    if doc_total is not None and all_totals and data.get("lines"):
        if abs(line_sum - doc_total) > TOL:
            flags.append(flag(
                "DOC_TOTAL_MISMATCH", "warn",
                f"Lines add up to {line_sum:,.2f}, but the document total is {doc_total:,.2f} "
                "(tax, freight or discounts may explain this)",
                "document_total",
            ))
    return flags


def build_flags(data: dict, match: dict) -> list[dict]:
    flags: list[dict] = []
    if not data.get("is_purchase_order", False):
        flags.append(flag("NOT_A_PO", "error",
                          f"This does not look like a purchase order ({data.get('document_type') or 'unknown type'})."))
        return flags
    if not data.get("po_number"):
        flags.append(flag("MISSING_PO_NUMBER", "warn",
                     "No PO number found.", "po_number"))
    if not data.get("lines"):
        flags.append(flag("NO_LINES", "error",
                     "No order lines found.", "lines"))

    cust = match.get("customer") or {}
    sel = cust.get("selected")
    if not sel:
        flags.append(flag("UNKNOWN_CUSTOMER", "error",
                          f"Customer '{data.get('customer_name') or '?'}' is not in Sage. Pick one or add it in Sage.",
                          "customer_name"))
    else:
        if sel["score"] < AUTO_ACCEPT:
            flags.append(flag("LOW_CONFIDENCE_CUSTOMER", "warn",
                              f"Customer matched to {sel['name']} with only {int(sel['score'] * 100)}% confidence.",
                              "customer_name"))
        cands = cust.get("candidates") or []
        if len(cands) > 1 and not cust.get("manual") and cands[0]["score"] - cands[1]["score"] < 0.05:
            flags.append(flag("AMBIGUOUS_SITE", "warn",
                              f"{cands[0]['name']} and {cands[1]['name']} match about equally - confirm the site.",
                              "customer_name"))

    for i, (ln, lm) in enumerate(zip(data.get("lines") or [], match.get("lines") or [])):
        n = i + 1
        if to_num(ln.get("unit_price")) is None:
            flags.append(flag("MISSING_PRICE", "error",
                         f"Line {n}: no unit price on the document.", f"lines.{i}.unit_price"))
        if to_num(ln.get("quantity")) is None:
            flags.append(flag("MISSING_QUANTITY", "error",
                         f"Line {n}: no quantity.", f"lines.{i}.quantity"))
        psel = lm.get("selected")
        if not psel:
            flags.append(flag("UNKNOWN_PRODUCT", "error",
                              f"Line {n}: '{ln.get('description') or '?'}' is not a product we sell.",
                              f"lines.{i}.description"))
        else:
            if psel["score"] < AUTO_ACCEPT:
                flags.append(flag("LOW_CONFIDENCE_PRODUCT", "warn",
                                  f"Line {n}: matched to {psel['code']} with {int(psel['score'] * 100)}% confidence - check it.",
                                  f"lines.{i}.description"))
            unit = (ln.get("unit") or "").strip().lower()
            if psel.get("unit") and unit and unit.rstrip("s") != str(psel["unit"]).lower().rstrip("s"):
                flags.append(flag("UNIT_MISMATCH", "warn",
                                  f"Line {n}: document is priced per {unit}, Sage product {psel['code']} is per {psel['unit']}. "
                                  "Quantity and price are NOT converted.", f"lines.{i}.unit"))
    flags.extend(check_math(data))

    conf = data.get("confidence")
    if isinstance(conf, (int, float)) and conf < 0.7:
        flags.append(flag("AI_UNSURE", "warn",
                     f"The AI reported low confidence ({int(conf * 100)}%). {data.get('notes') or ''}".strip()))
    return flags


def ai_status_for(flags: list[dict]) -> str:
    if any(f["code"] == "EXTRACTION_FAILED" for f in flags):
        return "failed"
    return "flagged" if any(f["severity"] in ("error", "warn") for f in flags) else "passed"


def blocking(flags: list[dict]) -> list[dict]:
    return [f for f in flags if f["severity"] == "error"]
