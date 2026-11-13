import re
from difflib import SequenceMatcher

AUTO_ACCEPT = 0.85
MIN_ACCEPT = 0.60

_ABBREV = {
    "ISD": "INDEPENDENT SCHOOL DISTRICT",
    "DEPT": "DEPARTMENT",
    "HOSP": "HOSPITAL",
    "UNIV": "UNIVERSITY",
    "CTY": "COUNTY",
    "&": "AND",
}
_STOP = {"THE", "OF", "AND", "INC", "LLC", "LTD",
         "LIMITED", "CO", "CORP", "CORPORATION"}


def normalize(text: str) -> str:
    t = (text or "").upper().replace("&", " AND ")
    t = re.sub(r"[^A-Z0-9 ]+", " ", t)
    words = []
    for w in t.split():
        words.extend(_ABBREV.get(w, w).split())
    return " ".join(words)


def tokens(text: str) -> set[str]:
    return {w for w in normalize(text).split() if w not in _STOP}


def _similarity(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    ratio = SequenceMatcher(None, " ".join(sorted(ta)),
                            " ".join(sorted(tb))).ratio()
    containment = len(ta & tb) / min(len(ta), len(tb))
    return round(0.5 * ratio + 0.5 * containment, 4)


def match_customer(name: str, address: str, customers: list[dict], limit: int = 3) -> list[dict]:
    context = f"{name or ''} {address or ''}"
    out = []
    for c in customers:
        base, _, site = c["name"].partition(" - ")
        score = _similarity(name, base)
        if site and tokens(site) and tokens(site) & tokens(context):
            score = min(1.0, score + 0.15)
        out.append({"code": c["code"], "name": c["name"], "sage_id": c.get(
            "sage_id"), "score": round(score, 2)})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:limit]


_FUEL_RULES = [
    ("ULG", re.compile(
        r"unleaded|gasoline|petrol|mogas|premium|regular|\bulg\b|\bpms\b|\bgas\b", re.I)),
    ("DSL-D", re.compile(r"dyed|off.?road|non.?road|\bred\b|agricultur", re.I)),
    ("DSL", re.compile(r"clear|highway|on.?road|ulsd|\bago\b", re.I)),
]
_DIESEL = re.compile(r"diesel|\bdsl\b|\bago\b", re.I)


def match_product(description: str, products: list[dict], limit: int = 3) -> list[dict]:
    desc = description or ""
    by_code = {p["code"]: p for p in products}
    scored: dict[str, float] = {}

    def put(code: str, score: float):
        if code in by_code:
            scored[code] = max(scored.get(code, 0), score)

    if _DIESEL.search(desc):
        if _FUEL_RULES[1][1].search(desc):
            put("DSL-D", 0.95)
        elif _FUEL_RULES[2][1].search(desc):
            put("DSL", 0.95)
        else:
            put("DSL", 0.72)
            put("DSL-D", 0.70)
    elif _FUEL_RULES[0][1].search(desc):
        put("ULG", 0.95)

    for p in products:
        s = _similarity(desc, p["description"])
        if s > scored.get(p["code"], 0):
            scored[p["code"]] = round(s * 0.9, 2)

    out = [
        {"code": c, "description": by_code[c]["description"], "unit": by_code[c].get("unit"),
         "sage_id": by_code[c].get("sage_id"), "score": round(s, 2)}
        for c, s in scored.items()
    ]
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:limit]
