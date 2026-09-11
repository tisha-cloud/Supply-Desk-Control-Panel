"""
Where a workforce actually lives, and which micro-market that argues for.

A client hands over a list of employee pincodes. This turns that into a ranking
of the micro-markets the desk trades, so an office is chosen by where people
commute from rather than by where the agent happens to have stock.

Two deliberate decisions:

  * The ranking is by headcount, not by distance. The brief was to pick the
    location the majority live nearest, and a median-distance score quietly
    favours a geographic centre that suits nobody - the point between two
    clusters is convenient for neither.

  * Every pincode carries its locality name through to the answer, and any
    pincode not in the table is reported rather than dropped. A silent drop
    would shift the majority without anyone noticing; a named miss can be
    corrected.

PINCODE_AREAS below is a working table, not an official register. The locality
names are what each pincode is commonly known as, and they are shown in the
result precisely so a wrong one is visible and can be fixed.
"""
import csv
import io
import re
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

import db

# Pincode -> (locality, micro-market code as used by the micro_markets table).
# Codes must match the database: CBD, KRM, WF, ORR, HSR Layout, Indiranagar,
# E-City, North-BLR, BG Road, JP-Nagar, Jayanagar, BTM, Kanakapura Rd.
PINCODE_AREAS: Dict[str, Tuple[str, str]] = {
    # --- central -----------------------------------------------------------
    "560001": ("MG Road / Bangalore GPO", "CBD"),
    "560002": ("Chickpet / City Market", "CBD"),
    "560005": ("Fraser Town", "CBD"),
    "560008": ("Ulsoor", "CBD"),
    "560009": ("Gandhinagar", "CBD"),
    "560020": ("Seshadripuram", "CBD"),
    "560025": ("Richmond Town", "CBD"),
    "560027": ("Shanthinagar / Wilson Garden", "CBD"),
    "560030": ("Wilson Garden", "CBD"),
    "560042": ("Shivajinagar", "CBD"),
    "560051": ("Vasanth Nagar", "CBD"),
    "560052": ("Kempegowda / Majestic", "CBD"),
    "560053": ("Chickpet", "CBD"),
    "560046": ("Fraser Town", "CBD"),
    "560047": ("Viveknagar", "CBD"),
    # --- Indiranagar and Domlur -------------------------------------------
    "560038": ("Indiranagar", "Indiranagar"),
    "560071": ("Domlur", "Indiranagar"),
    "560075": ("New Thippasandra", "Indiranagar"),
    "560033": ("Maruthi Seva Nagar", "Indiranagar"),
    "560093": ("CV Raman Nagar", "Indiranagar"),
    # --- Koramangala -------------------------------------------------------
    "560034": ("Koramangala", "KRM"),
    "560095": ("Koramangala 8th Block", "KRM"),
    # --- HSR ---------------------------------------------------------------
    "560102": ("HSR Layout", "HSR Layout"),
    # --- BTM ---------------------------------------------------------------
    "560029": ("Bommanahalli / Dharmaram", "BTM"),
    "560068": ("BTM Layout", "BTM"),
    # --- Outer Ring Road ---------------------------------------------------
    "560103": ("Bellandur", "ORR"),
    "560037": ("Marathahalli", "ORR"),
    "560087": ("Varthur", "ORR"),
    "560035": ("Carmelaram / Sarjapur Road", "ORR"),
    "560016": ("Ramamurthy Nagar", "ORR"),
    "560036": ("KR Puram", "ORR"),
    # --- Whitefield --------------------------------------------------------
    "560066": ("Whitefield", "WF"),
    "560067": ("Whitefield / ITPL", "WF"),
    "560048": ("Hoodi / Kadugodi", "WF"),
    "560017": ("Vimanapura", "WF"),
    # --- Electronic City and south-east ------------------------------------
    "560100": ("Electronic City", "E-City"),
    "560099": ("Electronic City Phase 2 / Anekal", "E-City"),
    "562106": ("Attibele", "E-City"),
    "561229": ("Jigani", "E-City"),
    # --- north -------------------------------------------------------------
    "560024": ("Sanjaynagar / Hebbal", "North-BLR"),
    "560032": ("RT Nagar", "North-BLR"),
    "560045": ("Lingarajapuram", "North-BLR"),
    "560064": ("Yelahanka", "North-BLR"),
    "560065": ("GKVK / Yelahanka", "North-BLR"),
    "560077": ("Kothanur / Hennur", "North-BLR"),
    "560092": ("Vidyaranyapura / Hebbal", "North-BLR"),
    "560094": ("Sanjaynagar", "North-BLR"),
    "560097": ("Vidyaranyapura", "North-BLR"),
    "560043": ("Banaswadi / Kalyan Nagar", "North-BLR"),
    "560031": ("Benson Town", "North-BLR"),
    "560300": ("Devanahalli", "North-BLR"),
    "562110": ("Devanahalli", "North-BLR"),
    "560006": ("Jalahalli", "North-BLR"),
    "560013": ("Jalahalli East", "North-BLR"),
    "560015": ("Peenya", "North-BLR"),
    "560022": ("Yeshwanthpur", "North-BLR"),
    "560054": ("Mathikere", "North-BLR"),
    "560057": ("Peenya", "North-BLR"),
    "560058": ("Jalahalli", "North-BLR"),
    "560073": ("Chikkabanavara", "North-BLR"),
    "560091": ("Nagasandra", "North-BLR"),
    # --- Bannerghatta Road -------------------------------------------------
    "560076": ("Bannerghatta Road", "BG Road"),
    "560083": ("Bannerghatta", "BG Road"),
    # --- JP Nagar ----------------------------------------------------------
    "560078": ("JP Nagar", "JP-Nagar"),
    "560062": ("Konanakunte", "JP-Nagar"),
    # --- Jayanagar ---------------------------------------------------------
    "560011": ("Jayanagar", "Jayanagar"),
    "560041": ("Jayanagar 4th Block", "Jayanagar"),
    "560069": ("Jayanagar", "Jayanagar"),
    "560004": ("Basavanagudi", "Jayanagar"),
    # --- Kanakapura Road ---------------------------------------------------
    "560061": ("Uttarahalli", "Kanakapura Rd"),
    "560070": ("Banashankari / Padmanabhanagar", "Kanakapura Rd"),
    "560085": ("Banashankari 3rd Stage", "Kanakapura Rd"),
    "560050": ("Banashankari", "Kanakapura Rd"),
    "560109": ("Kanakapura Road", "Kanakapura Rd"),
    # --- west (no micro-market of its own; nearest the CBD) ----------------
    "560003": ("Malleswaram", "CBD"),
    "560010": ("Rajajinagar", "CBD"),
    "560012": ("IISc / Malleswaram", "CBD"),
    "560018": ("Chamrajpet", "CBD"),
    "560019": ("Hanumanthanagar", "CBD"),
    "560021": ("Srirampuram", "CBD"),
    "560023": ("Govindarajnagar", "CBD"),
    "560026": ("Vijayanagar", "CBD"),
    "560040": ("Vijayanagar", "CBD"),
    "560055": ("Malleswaram", "CBD"),
    "560079": ("Basaveshwaranagar", "CBD"),
    "560080": ("Sadashivanagar", "CBD"),
    "560086": ("Mahalakshmipuram", "CBD"),
    "560096": ("Nandini Layout", "CBD"),
    "560072": ("Nagarbhavi", "CBD"),
    "560056": ("Kengeri / Bangalore University", "CBD"),
    "560059": ("Rajarajeshwari Nagar", "CBD"),
    "560060": ("Kengeri", "CBD"),
    "560098": ("RR Nagar", "CBD"),
}

# Any six-digit number is a candidate pincode, not only Karnataka ones.
# Matching just 5xxxxx made an employee in Mumbai or Delhi vanish from the
# workforce rather than be reported as living outside the city, which shifts
# the majority without anyone seeing it happen. A six-digit staff number would
# be picked up here too, and it lands in the unrecognised list where it is
# visible and can be dealt with.
PINCODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


# The mapping is cached briefly: one profiling run reads it once rather than
# once per pincode, and an edit takes effect within the minute.
_AREAS_TTL = 60.0
_areas_cache: Dict[str, Any] = {"at": 0.0, "value": None}


def load_areas(force: bool = False) -> Dict[str, Tuple[str, str]]:
    """
    The pincode mapping, from the database, falling back to the seed above.

    PINCODE_AREAS is where this started and is now only a starting point. The
    desk knows Bengaluru better than the code does, and a correction should not
    need a deploy - so the table is copied into `pincode_areas` once and edited
    there afterwards.
    """
    now = time.time()
    if not force and _areas_cache["value"] is not None:
        if now - _areas_cache["at"] < _AREAS_TTL:
            return _areas_cache["value"]

    areas = dict(PINCODE_AREAS)
    try:
        rows = db.client().table("pincode_areas").select(
            "pincode, locality, micro_market").limit(5000).execute().data or []
        if rows:
            # The database wins outright where it has a pincode, so an edit is
            # never quietly overridden by the seed it came from.
            for row in rows:
                areas[str(row["pincode"]).strip()] = (
                    row.get("locality") or "", row["micro_market"])
    except Exception:
        # No table yet, or no database: the seed alone still answers.
        pass

    _areas_cache.update({"at": now, "value": areas})
    return areas


def forget_areas() -> None:
    """Drop the cache, so an import shows up immediately."""
    _areas_cache.update({"at": 0.0, "value": None})


def seed_areas() -> int:
    """
    Copy the built-in table into the database, once, if it is empty.

    Only ever into an empty table: re-seeding would undo corrections, and the
    whole point of moving the mapping into the database was that corrections
    stick.
    """
    sb = db.client()
    try:
        if sb.table("pincode_areas").select("pincode").limit(1).execute().data:
            return 0
    except Exception:
        return 0     # the table does not exist yet; migration 0007 not run

    known = {r["code"] for r in
             (sb.table("micro_markets").select("code").execute().data or [])}
    rows = [{"pincode": pincode, "locality": locality,
             "micro_market": code, "source": "seed"}
            for pincode, (locality, code) in PINCODE_AREAS.items()
            if code in known]
    if rows:
        sb.table("pincode_areas").insert(rows).execute()
    forget_areas()
    return len(rows)


def import_areas(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Bulk-load a pincode list, replacing any entry it names.

    Returns what it wrote and, more usefully, what it refused: a row naming a
    micro-market the database does not have would produce a recommendation
    pointing nowhere, so it is rejected and reported rather than stored.
    """
    sb = db.client()
    known = {r["code"] for r in
             (sb.table("micro_markets").select("code").execute().data or [])}

    payload, rejected = [], []
    seen = set()
    for row in rows:
        pincode = re.sub(r"\D", "", str(row.get("pincode") or ""))
        market = str(row.get("micro_market") or "").strip()
        locality = str(row.get("locality") or "").strip()
        if len(pincode) != 6:
            rejected.append({"row": row, "why": "not a six-digit pincode"})
            continue
        if market not in known:
            rejected.append({"row": row,
                             "why": "no micro-market called %r" % market})
            continue
        if pincode in seen:
            continue     # last one in the file would win anyway; keep the first
        seen.add(pincode)
        payload.append({"pincode": pincode, "locality": locality or market,
                        "micro_market": market, "source": "import"})

    if payload:
        sb.table("pincode_areas").upsert(payload, on_conflict="pincode").execute()
    forget_areas()
    return {"imported": len(payload), "rejected": rejected,
            "micro_markets": sorted(known)}


# Header names the upload reader will accept for each column, so a file does
# not have to be reshaped before it can be loaded.
COLUMN_ALIASES = {
    "pincode": ("pincode", "pin code", "pin", "postal code", "zip", "zipcode"),
    "locality": ("locality", "area", "location", "place", "neighbourhood",
                 "neighborhood", "post office"),
    "micro_market": ("micro_market", "micro market", "micromarket", "market",
                     "micro-market", "blr categorization", "categorization",
                     "category"),
}


def read_area_upload(data: bytes, filename: str = "") -> List[Dict[str, str]]:
    """
    Read a pincode mapping file, working out which column is which.

    Accepts whatever shape the list arrives in - the headers only have to be
    recognisable, not exact - because asking for a specific layout just moves
    the work onto whoever has the data.
    """
    table: List[List[str]] = []
    name = (filename or "").lower()

    if name.endswith((".xlsx", ".xlsm", ".xls")):
        try:
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            for row in wb.worksheets[0].iter_rows(values_only=True):
                table.append(["" if c is None else str(c).strip() for c in row])
        except Exception:
            return []
    else:
        text = data.decode("utf-8", "replace")
        table = [[c.strip() for c in row] for row in csv.reader(io.StringIO(text))]

    table = [r for r in table if any(c for c in r)]
    if not table:
        return []

    header = [c.lower().strip() for c in table[0]]
    index: Dict[str, int] = {}
    for field, aliases in COLUMN_ALIASES.items():
        for position, cell in enumerate(header):
            if cell in aliases:
                index[field] = position
                break

    # No recognisable header: assume the conventional order instead of giving
    # up, since a bare two- or three-column list is the common case.
    body = table[1:] if index else table
    if not index:
        index = {"pincode": 0, "locality": 1, "micro_market": 2}

    rows = []
    for raw in body:
        def cell(field: str) -> str:
            position = index.get(field)
            return raw[position] if position is not None and position < len(raw) else ""
        if cell("pincode"):
            rows.append({"pincode": cell("pincode"),
                         "locality": cell("locality"),
                         "micro_market": cell("micro_market")})
    return rows


def extract_pincodes(text: str) -> List[str]:
    """
    Every six-digit pincode in a blob of text, in the order they appear.

    Deliberately forgiving about what it is handed: a pasted column, a
    comma-separated line, or the text of a spreadsheet all read the same. Each
    occurrence counts, because one row is one employee.
    """
    return PINCODE_RE.findall(text or "")


def read_upload(data: bytes, filename: str = "") -> List[str]:
    """Pull pincodes out of an uploaded CSV, spreadsheet or text file."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        try:
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            found: List[str] = []
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    for cell in row:
                        if cell is not None:
                            found += extract_pincodes(str(cell))
            return found
        except Exception:
            return []

    text = data.decode("utf-8", "replace")
    if name.endswith(".csv"):
        found = []
        for row in csv.reader(io.StringIO(text)):
            for cell in row:
                found += extract_pincodes(cell)
        return found
    return extract_pincodes(text)


def available_markets() -> Dict[str, int]:
    """
    Micro-market codes the desk actually has stock in, with building counts.

    A market nobody can be housed in is not a recommendation, however many
    employees live beside it.
    """
    try:
        rows = db.client().table("buildings").select(
            "micro_markets(code)").limit(2000).execute().data or []
    except Exception:
        return {}
    counts: Counter = Counter()
    for row in rows:
        code = (row.get("micro_markets") or {}).get("code")
        if code:
            counts[code] += 1
    return dict(counts)


def profile(pincodes: List[str]) -> Dict[str, Any]:
    """
    Rank micro-markets by how many of these employees live in each.

    Returns the ranking, the per-pincode breakdown behind it, and anything the
    table did not recognise - so the recommendation can be checked rather than
    taken on trust.
    """
    counts = Counter(p.strip() for p in pincodes if p and p.strip())
    total = sum(counts.values())
    areas = load_areas()

    stock = available_markets()
    markets: Dict[str, Dict[str, Any]] = {}
    unknown: List[Dict[str, Any]] = []

    for pincode, employees in counts.items():
        entry = areas.get(pincode)
        if not entry:
            unknown.append({"pincode": pincode, "employees": employees})
            continue
        locality, code = entry
        bucket = markets.setdefault(code, {
            "micro_market": code, "employees": 0, "areas": [],
            "buildings": stock.get(code, 0),
        })
        bucket["employees"] += employees
        bucket["areas"].append({"pincode": pincode, "locality": locality,
                                "employees": employees})

    for bucket in markets.values():
        bucket["areas"].sort(key=lambda a: -a["employees"])
        bucket["share"] = round(100.0 * bucket["employees"] / total, 1) if total else 0.0

    # Most people first. Where two markets tie, the one with more stock wins,
    # because it is the one a requirement can actually be met in.
    ranked = sorted(markets.values(),
                    key=lambda m: (-m["employees"], -m["buildings"], m["micro_market"]))

    matched = sum(m["employees"] for m in ranked)
    with_stock = [m for m in ranked if m["buildings"] > 0]

    return {
        "total_employees": total,
        "matched_employees": matched,
        "unrecognised_employees": total - matched,
        "unrecognised": sorted(unknown, key=lambda u: -u["employees"]),
        "markets": ranked,
        # The answer to "where should they sit": the market most of them live
        # nearest that the desk can actually house them in.
        "recommended": with_stock[0]["micro_market"] if with_stock else None,
        "recommended_share": with_stock[0]["share"] if with_stock else 0.0,
    }
