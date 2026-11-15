NOTE = (
    "Mock mode: no AI was used. These values are placeholders, not read from the document. "
    "Reviewer must check and fill in every field."
)

TENDER_KEYS = ("kisumu", "bomet", "tender", "framework")
INVOICE_KEYS = ("invoice", "receipt", "proforma")

PO_PROFILES = [
    ("sandiego", {
        "customer_name": "City of San Diego",
        "po_number": "4500101461",
        "delivery_address": "Landfill site",
        "unit": "gallon",
        "currency": "USD",
    }),
    ("garland", {
        "customer_name": "Garland ISD",
        "po_number": None,
        "delivery_address": "Garland, TX",
        "unit": "gallon",
        "currency": "USD",
    }),
    ("mbeya", {
        "customer_name": "Mbeya Zonal Referral Hospital",
        "po_number": None,
        "delivery_address": "Mbeya, Tanzania",
        "unit": "litre",
        "currency": "TZS",
    }),
]


def _base(is_po: bool, doc_type: str) -> dict:
    return {
        "is_purchase_order": is_po,
        "document_type": doc_type,
        "customer_name": None,
        "po_number": None,
        "po_date": None,
        "delivery_address": None,
        "currency": None,
        "document_total": None,
        "lines": [],
        "confidence": 0.4,
        "notes": NOTE,
        "mock": True,
    }


def mock_extract(filename: str, hints: str | None = None) -> dict:
    name = (filename or "").lower()
    if any(k in name for k in TENDER_KEYS):
        return _base(False, "tender")
    if any(k in name for k in INVOICE_KEYS):
        return _base(False, "invoice")
    data = _base(True, "purchase order")
    unit = None
    for key, profile in PO_PROFILES:
        if key in name:
            data["customer_name"] = profile["customer_name"]
            data["po_number"] = profile["po_number"]
            data["delivery_address"] = profile["delivery_address"]
            unit = profile["unit"]
            data["currency"] = profile["currency"]
            break
    data["lines"] = [{
        "description": "Diesel",
        "quantity": None,
        "unit": unit,
        "unit_price": None,
        "line_total": None,
    }]
    return data
