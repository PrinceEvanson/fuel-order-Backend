import time

from sqlalchemy.orm import Session

from . import sage_client

SAMPLE_CUSTOMERS = [
    {"code": "TAM001", "name": "TEXAS A&M AGRILIFE RESEARCH - PLAINVIEW", "sage_id": None},
    {"code": "TAM002", "name": "TEXAS A&M AGRILIFE RESEARCH - MCGREGOR", "sage_id": None},
    {"code": "SDG001", "name": "CITY OF SAN DIEGO - ENVIRONMENTAL SERVICES", "sage_id": None},
    {"code": "GAR001", "name": "GARLAND INDEPENDENT SCHOOL DISTRICT", "sage_id": None},
    {"code": "MBY001", "name": "MBEYA ZONAL REFERRAL HOSPITAL", "sage_id": None},
]
SAMPLE_PRODUCTS = [
    {"code": "ULG", "description": "Unleaded gasoline", "unit": "gallon", "sage_id": None},
    {"code": "DSL", "description": "Diesel (clear / highway)", "unit": "gallon", "sage_id": None},
    {"code": "DSL-D", "description": "Diesel (dyed / off-road)", "unit": "gallon", "sage_id": None},
]
_UNITS = {p["code"]: p["unit"] for p in SAMPLE_PRODUCTS}

_cache: dict = {"at": 0.0, "value": None}
_TTL = 60

def get_catalog(db: Session) -> dict:
    if not sage_client.is_connected(db):
        return {"customers": SAMPLE_CUSTOMERS, "products": SAMPLE_PRODUCTS, "source": "sample", "error": None}
    if _cache["value"] and time.time() - _cache["at"] < _TTL:
        return _cache["value"]
    try:
        customers = [
            {"code": c.get("reference") or "", "name": c["name"], "sage_id": c["id"]}
            for c in sage_client.list_customers(db)
        ]
        products = [
            {"code": p.get("item_code") or "", "description": p.get("description") or p.get("displayed_as", ""),
             "unit": _UNITS.get(p.get("item_code") or ""), "sage_id": p["id"]}
            for p in sage_client.list_products(db)
        ]
        value = {"customers": customers, "products": products, "source": "sage", "error": None}
        _cache.update(at=time.time(), value=value)
        return value
    except sage_client.SageError as e:
        return {"customers": [], "products": [], "source": "sage", "error": str(e)}

def clear_cache() -> None:
    _cache.update(at=0.0, value=None)
