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

    stock = available_markets()
    markets: Dict[str, Dict[str, Any]] = {}
    unknown: List[Dict[str, Any]] = []

    for pincode, employees in counts.items():
        entry = PINCODE_AREAS.get(pincode)
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
