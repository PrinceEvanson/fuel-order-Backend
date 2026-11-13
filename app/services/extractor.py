import base64

import anthropic

from ..config import settings

PO_TOOL = {
    "name": "record_purchase_order",
    "description": "Record what the document says. Use null for anything not printed on it. Never guess or calculate values.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_purchase_order": {"type": "boolean", "description": "True only if the document contains an actual purchase order / LPO / fuel order to extract. False for tenders, invoices-only, receipts, brochures, etc."},
            "document_type": {"type": "string", "description": "e.g. purchase order, LPO, tender, invoice, receipt, other"},
            "customer_name": {"type": ["string", "null"], "description": "The BUYER (who is ordering), not the supplier"},
            "po_number": {"type": ["string", "null"]},
            "po_date": {"type": ["string", "null"], "description": "ISO date YYYY-MM-DD if possible"},
            "delivery_address": {"type": ["string", "null"], "description": "Delivery / ship-to location incl. site name"},
            "currency": {"type": ["string", "null"], "description": "ISO code or symbol as printed"},
            "document_total": {"type": ["number", "null"], "description": "Grand total as printed"},
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "quantity": {"type": ["number", "null"]},
                        "unit": {"type": ["string", "null"], "description": "gallon, litre, etc. as printed"},
                        "unit_price": {"type": ["number", "null"]},
                        "line_total": {"type": ["number", "null"]},
                    },
                    "required": ["description"],
                },
            },
            "confidence": {"type": "number", "description": "0-1: how sure you are that the extraction is right (lower for poor scans)"},
            "page_with_order": {"type": ["integer", "null"], "description": "Page number where the order was found, if inside a longer document"},
            "notes": {"type": "string", "description": "Anything unclear, illegible, or suspicious"},
        },
        "required": ["is_purchase_order", "document_type", "lines", "confidence"],
    },
}

PROMPT = (
    "Extract the purchase order from this document. It may be a scan with OCR noise, may be priced in "
    "gallons or litres, and the order may be buried inside a longer document (e.g. a bid or tender with a "
    "sample PO). Copy values exactly as printed; do not correct arithmetic and do not convert units. "
    "If a price is missing, leave it null. If there is no real purchase order, set is_purchase_order=false. "
    "Include fuel lines only if they are order lines (not general terms)."
)


class ExtractionError(Exception):
    pass


def extract_po(pdf_bytes: bytes, hints: str | None = None) -> dict:
    if not settings.ANTHROPIC_API_KEY:
        raise ExtractionError(
            "ANTHROPIC_API_KEY is not configured on the server.")
    client = anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY, timeout=120)
    text = PROMPT
    if hints:
        text += (
            "\n\nA person reviewed a previous attempt and reported these problems. Re-read the document "
            f"carefully with them in mind, but only report what is actually printed:\n{hints}"
        )
    try:
        resp = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=8192,
            tools=[PO_TOOL],
            tool_choice={"type": "tool", "name": PO_TOOL["name"]},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                    "data": base64.standard_b64encode(pdf_bytes).decode()}},
                    {"type": "text", "text": text},
                ],
            }],
        )
    except anthropic.APIStatusError as e:
        raise ExtractionError(
            f"The AI service rejected the request ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise ExtractionError(
            "Could not reach the AI service. Please try again.")
    for block in resp.content:
        if block.type == "tool_use" and block.name == PO_TOOL["name"]:
            return block.input
    raise ExtractionError(
        "The AI did not return a structured result. Please try again or redo the scan.")
