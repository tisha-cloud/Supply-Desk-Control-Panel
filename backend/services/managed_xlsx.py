"""
Imports 'BLR - Managed Office Space Supply 2026.xlsx' into Supabase.

Two things make this workbook awkward:

1. It is transposed. Each micro-market sheet is an attribute stack - the row
   labels are the fields ("Building Name", "Quoted Rental...") and each COLUMN
   is one option. So we read down a column to build one record.

2. It is 318MB, and essentially all of that is 398 embedded photographs. The
   images are not reachable from openpyxl's read-only mode, and loading the
   workbook in normal mode to reach them would need gigabytes of RAM. Instead
   we walk the .xlsx zip ourselves: worksheet -> drawing -> anchor -> media
   part, which gives us both the image bytes and the (row, column) it sits on.
   Because the photographs sit on the "Building Perspective" row, the anchor
   column tells us which option each photo belongs to.
"""
import io
import os
import re
import zipfile
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

import openpyxl

import db
from extractor import schema

NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}
R_EMBED = "{%s}embed" % NS["rel"]
R_ID = "{%s}id" % NS["rel"]

# Sheets that are reference data rather than supply inventory.
NON_SUPPLY_SHEETS = {
    "blr - categorization", "micro-markets", "operators",
    "cbd-managed office list", "cbd - builders - developers", "master file",
}

# Reference sheets we DO read, for what they say about the operators themselves.
OPERATORS_SHEET = "operators"
OFFERINGS_SHEET = "cbd-managed office list"

OFFERING_VALUES = {"yes": "yes", "limited": "limited", "no": "no"}


def _offering(value):
    """'Yes' / 'Limited' / 'No' -> the offering_level enum, else None."""
    return OFFERING_VALUES.get(_norm(value))


# Short forms the supply sheets use that no amount of string matching recovers.
OPERATOR_ALIASES = {
    "uv": "Urban Vault",
    "ts": "Table Space",
    "tec": "The Executive Centre (TEC)",
}


def _op_key(name: str) -> str:
    """Comparison key: lowercase, alphanumerics only. 'Red Brick' -> 'redbrick'."""
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def _first_token(name: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+", str(name or ""))
    return tokens[0].lower() if tokens else ""


def resolve_operator(raw: str, canonical: List[str]) -> str:
    """
    Map an operator label from a supply sheet onto its canonical company.

    The supply sheets name operators loosely - case drifts ('Wework' vs
    'WeWork India'), abbreviations appear ('UV', 'TS'), and sub-brands are
    written as if they were separate companies ('BHIVE Platinum',
    '315Work Avenue DLR1'). Left alone that turns 37 operators into 56, which
    is what makes a shared database stop being useful.
    """
    if not raw:
        return raw
    raw = raw.strip()
    key = _op_key(raw)
    if not key:
        return raw

    alias = OPERATOR_ALIASES.get(key)
    if alias:
        return alias

    by_key = {_op_key(c): c for c in canonical}
    if key in by_key:
        return by_key[key]

    # Sub-brands share the company's leading word: 'BHIVE Platinum' -> 'BHIVE Workspace'.
    head = _first_token(raw)
    if len(head) >= 3:
        for name in canonical:
            if _first_token(name) == head:
                return name

    # One is a longer form of the other: 'Novel' -> 'Novel Office'.
    for candidate_key, name in by_key.items():
        if len(key) >= 4 and (candidate_key.startswith(key) or key.startswith(candidate_key)):
            return name

    # Last resort for spelling drift: 'CorporatEdge' -> 'CorporateEdge'.
    best, score = None, 0.0
    for candidate_key, name in by_key.items():
        ratio = SequenceMatcher(None, key, candidate_key).ratio()
        if ratio > score:
            best, score = name, ratio
    return best if score >= 0.88 else raw


def collect_operator_labels(workbook) -> List[str]:
    """Every operator prefix used across the supply sheets."""
    labels: List[str] = []
    for sheet_name in workbook.sheetnames:
        if _norm(sheet_name) in NON_SUPPLY_SHEETS:
            continue
        rows = list(workbook[sheet_name].iter_rows(values_only=True))
        if not rows or _norm(rows[0][0]) != "particulars":
            continue
        name_row = next((r for r in rows if _norm(r[0]) == "building name"), None)
        if not name_row:
            continue
        for cell in name_row[1:]:
            text = _text(cell)
            if not text:
                continue
            split = re.split(r"\s+-\s+", text, maxsplit=1)
            if len(split) == 2 and len(split[0]) <= 24:
                label = split[0].strip()
                if label and label not in labels:
                    labels.append(label)
    return labels


def build_operator_map(workbook) -> Dict[str, str]:
    """
    raw label -> canonical operator, for every label in the workbook.

    Resolution runs in two passes. The first maps each label onto the
    Operators sheet. The second groups whatever is left against itself, so an
    operator the workbook forgot to list ('Bizzhub', 'Bizzhub Aspire',
    'Bizzhub ESQUIRE') still collapses to one company instead of three.
    """
    canonical = canonical_operator_names(workbook)
    labels = collect_operator_labels(workbook)

    mapping: Dict[str, str] = {}
    unresolved: List[str] = []
    for label in labels:
        resolved = resolve_operator(label, canonical)
        if resolved == label and _op_key(label) not in {_op_key(c) for c in canonical}:
            unresolved.append(label)
        else:
            mapping[label] = resolved

    by_head: Dict[str, List[str]] = {}
    for label in unresolved:
        by_head.setdefault(_first_token(label), []).append(label)
    for head, group in by_head.items():
        # the shortest label is the bare company name; the rest are sub-brands
        leader = min(group, key=len)
        for label in group:
            mapping[label] = leader

    return mapping


def canonical_operator_names(workbook) -> List[str]:
    """The operator list the workbook itself considers authoritative."""
    sheet_name = next((n for n in workbook.sheetnames if _norm(n) == OPERATORS_SHEET), None)
    if not sheet_name:
        return []
    names = []
    for row in workbook[sheet_name].iter_rows(min_row=2, values_only=True):
        name = _text(row[1] if len(row) > 1 else None)
        if name and name not in names:
            names.append(name)
    return names

CONTENT_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
    ".emf": "image/emf", ".wmf": "image/wmf",
}

# Row label -> field. Matched by normalised "contains", so wording drift
# ("Total Building Size (SBA) [In Sq. Ft.]") still lands.
FIELD_PATTERNS: List[Tuple[str, str]] = [
    ("building_name",           r"building name"),
    ("address",                 r"^address"),
    ("photo",                   r"building perspective|photograph"),
    ("building_details",        r"building details"),
    ("developer",               r"developer|landlord"),
    ("structure",               r"building structure"),
    ("total_size",              r"total building size"),
    ("avg_floor_plate",         r"average floor plate"),
    ("floor_plate_efficiency",  r"floor plate efficiency"),
    ("power_kva",               r"^power \["),
    ("power_backup",            r"power back"),
    ("proposed_space",          r"proposed space"),
    ("offered",                 r"offered seats|area offered"),
    ("floor_offered",           r"floor offered"),
    ("status",                  r"^status"),
    ("fitout",                  r"fit-?out details"),
    ("timeline",                r"^timeline"),
    ("parking_ratio",           r"car parking ratio"),
    ("commercial_terms",        r"commercial terms"),
    ("rent",                    r"quoted rental"),
    ("cam",                     r"cam charges"),
    ("parking_charges",         r"car parking charges"),
    ("escalation",              r"rental escalation"),
    ("deposit",                 r"security deposit|refundable"),
    ("tenure",                  r"lease tenure"),
    ("lock_in",                 r"lock-?in"),
    ("notice",                  r"notice period"),
    ("oc",                      r"occupancy certificate"),
    ("location_map",            r"location map"),
    ("contact_person",          r"contact person"),
    ("contact_number",          r"contact number"),
    ("contact_email",           r"official email|email id"),
]


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _field_for_label(label: Any) -> Optional[str]:
    text = _norm(label)
    if not text:
        return None
    for field, pattern in FIELD_PATTERNS:
        if re.search(pattern, text):
            return field
    return None


def _num(value: Any) -> Optional[float]:
    """'60,500-60,700 Sft' -> 60500.0 ; '80% (+/- 2%)' -> 80.0 ; '' -> None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    number = float(match.group(1))
    low = text.lower()
    if re.search(r"\bmn\b|million", low):
        number *= 1_000_000
    elif re.search(r"lakh|lacs?", low):
        number *= 100_000
    return number


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or text.lower() in ("none", "nan", "n/a", "na", "-", "tbd"):
        return None
    return text


# The quantity and the rate are written into separate rows and each has its own
# ambiguous unit, so they are classified independently. Letting one infer the
# other propagates a single misreading into both fields: a 30,000 sq ft suite
# quoted at a per-seat rate would become "30,000 seats", and a 63-seat centre
# quoted per square foot would become "63 sq ft".
SEAT_RATE_FLOOR = 1000        # a monthly rate at or above this is per seat
SQFT_RATE_CEILING = 500       # at or below this it is per square foot
AREA_QUANTITY_FLOOR = 5000    # a quantity above this is an area, not a seat count


def classify_offering(offered):
    """"seats" or "area" - what the offered quantity is counted in."""
    if not offered or offered <= 0:
        return None
    return "area" if offered > AREA_QUANTITY_FLOOR else "seats"


def classify_rate(rate):
    """
    "seat", "sqft", or None when the magnitude does not settle it.

    This used to depend on whether a seat count was present, so an option with
    a per-seat rate but no seat count had its rate filed as rent per square
    foot - which is how thirteen rows ended up quoting a median of Rs 9,500
    per square foot per month.
    """
    if not rate or rate <= 0:
        return None
    if rate >= SEAT_RATE_FLOOR:
        return "seat"
    if rate <= SQFT_RATE_CEILING:
        return "sqft"
    return None


def offering_mismatch(offering, rate_unit):
    """A note when the quantity and the rate disagree, for a human to check."""
    if not offering or not rate_unit:
        return None
    if offering == "area" and rate_unit == "seat":
        return "quantity reads as an area but the rate reads as per-seat"
    if offering == "seats" and rate_unit == "sqft":
        return "quantity reads as seats but the rate reads as per-sq-ft"
    return None


def _latlng(value: Any) -> Tuple[Optional[float], Optional[float]]:
    text = _text(value) or ""
    match = re.match(r"^\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*$", text)
    if match:
        return float(match.group(1)), float(match.group(2))
    return None, None


# --------------------------------------------------------------- image mapping
def map_sheet_images(xlsx_path: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Returns {sheet_name: [{col, row, part, ext}, ...]} without loading any
    image bytes. `col` and `row` are zero-based anchor coordinates.
    """
    result: Dict[str, List[Dict[str, Any]]] = {}
    with zipfile.ZipFile(xlsx_path) as z:
        names = set(z.namelist())

        # sheet name -> worksheet part
        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        wb_rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rel_target = {r.get("Id"): r.get("Target") for r in wb_rels}

        sheet_parts: Dict[str, str] = {}
        for sheet in workbook.find("main:sheets", NS):
            target = rel_target.get(sheet.get(R_ID), "")
            if not target:
                continue
            target = target.lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target
            sheet_parts[sheet.get("name")] = target

        for sheet_name, part in sheet_parts.items():
            rels_part = os.path.dirname(part) + "/_rels/" + os.path.basename(part) + ".rels"
            if rels_part not in names:
                continue
            sheet_rels = ET.fromstring(z.read(rels_part))
            drawing_target = next(
                (r.get("Target") for r in sheet_rels
                 if (r.get("Type") or "").endswith("/drawing")), None)
            if not drawing_target:
                continue

            drawing_part = os.path.normpath(
                os.path.join(os.path.dirname(part), drawing_target)).replace("\\", "/")
            if drawing_part not in names:
                continue

            drawing_rels_part = (os.path.dirname(drawing_part) + "/_rels/"
                                 + os.path.basename(drawing_part) + ".rels")
            embed_target = {}
            if drawing_rels_part in names:
                drawing_rels = ET.fromstring(z.read(drawing_rels_part))
                for rel in drawing_rels:
                    media = os.path.normpath(
                        os.path.join(os.path.dirname(drawing_part), rel.get("Target"))
                    ).replace("\\", "/")
                    embed_target[rel.get("Id")] = media

            entries = []
            drawing = ET.fromstring(z.read(drawing_part))
            for anchor in drawing:
                frm = anchor.find("xdr:from", NS)
                if frm is None:
                    continue
                col = int(frm.find("xdr:col", NS).text or 0)
                row = int(frm.find("xdr:row", NS).text or 0)
                blip = anchor.find(".//a:blip", NS)
                if blip is None:
                    continue
                media = embed_target.get(blip.get(R_EMBED))
                if not media or media not in names:
                    continue
                entries.append({
                    "col": col, "row": row, "part": media,
                    "ext": os.path.splitext(media)[1].lower(),
                })
            if entries:
                result[sheet_name] = entries
    return result


# ------------------------------------------------------------------- importing
def import_workbook(xlsx_path: str, job_id: Optional[str] = None,
                    upload_images: bool = True, supply_type: str = "managed",
                    dry_run: bool = False) -> Dict[str, Any]:
    """
    Parse the workbook and write it into Supabase. Returns a stats dict.

    `supply_type` tags every building this workbook describes - it is the
    Managed Office Space supply file, so the default is 'managed'. Operators
    that also run coworking are recorded on the organisation, not by
    reclassifying their buildings.

    With `dry_run` the workbook is parsed and counted but nothing is written,
    which is how the parse gets checked before it touches the database.
    """
    stats = {"sheets": 0, "buildings": 0, "spaces": 0, "images": 0,
             "operators": 0, "contacts": 0, "skipped": 0, "errors": [],
             "supply_type": supply_type, "dry_run": dry_run,
             "sample": []}

    db.append_job_log(job_id, "Mapping embedded images ...")
    try:
        images_by_sheet = map_sheet_images(xlsx_path)
        total_images = sum(len(v) for v in images_by_sheet.values())
        db.append_job_log(job_id, "Found %d embedded images across %d sheets."
                          % (total_images, len(images_by_sheet)))
    except Exception as exc:
        images_by_sheet = {}
        stats["errors"].append("image mapping failed: %s" % exc)
        db.append_job_log(job_id, "Image mapping failed: %s" % exc)

    workbook = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    supply_sheets = [n for n in workbook.sheetnames if _norm(n) not in NON_SUPPLY_SHEETS]
    db.update_job(job_id, total_files=len(supply_sheets), status="running")

    operator_map = build_operator_map(workbook)

    # Operators first: buildings reference them, and the offering flags live here.
    try:
        operator_stats = _import_operators(workbook, dry_run)
        stats["operators"] += operator_stats["operators"]
        stats["contacts"] += operator_stats["contacts"]
        db.append_job_log(job_id, "Operators: %d organisations, %d contacts."
                          % (operator_stats["operators"], operator_stats["contacts"]))
    except Exception as exc:
        stats["errors"].append("operator import failed: %s" % exc)
        db.append_job_log(job_id, "Operator import failed: %s" % exc)

    zip_handle = zipfile.ZipFile(xlsx_path) if upload_images else None
    try:
        for index, sheet_name in enumerate(supply_sheets, start=1):
            worksheet = workbook[sheet_name]
            rows = list(worksheet.iter_rows(values_only=True))
            if not rows or _norm(rows[0][0]) != "particulars":
                stats["skipped"] += 1
                db.append_job_log(job_id, "Skipped '%s' (not an option-stack sheet)." % sheet_name)
                db.update_job(job_id, done_files=index)
                continue

            sheet_stats = _import_sheet(
                sheet_name, rows, images_by_sheet.get(sheet_name, []),
                zip_handle, job_id, supply_type, dry_run, operator_map)
            stats["sample"].extend(sheet_stats.pop("sample", [])[:3])
            for key in ("buildings", "spaces", "images", "contacts"):
                stats[key] += sheet_stats[key]
            stats["sheets"] += 1

            db.append_job_log(job_id, "%s: %d buildings, %d images."
                              % (sheet_name, sheet_stats["buildings"], sheet_stats["images"]))
            db.update_job(job_id, done_files=index,
                          buildings_upserted=stats["buildings"],
                          spaces_upserted=stats["spaces"],
                          images_uploaded=stats["images"])
    finally:
        if zip_handle:
            zip_handle.close()
        workbook.close()

    return stats


def _import_sheet(sheet_name: str, rows: List[Tuple], image_entries: List[Dict[str, Any]],
                  zip_handle: Optional[zipfile.ZipFile], job_id: Optional[str],
                  supply_type: str = "managed", dry_run: bool = False,
                  operator_map: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    stats: Dict[str, Any] = {"buildings": 0, "spaces": 0, "images": 0,
                             "contacts": 0, "sample": []}

    # row index (0-based) -> field name
    field_rows: Dict[str, int] = {}
    for idx, row in enumerate(rows):
        field = _field_for_label(row[0] if row else None)
        if field and field not in field_rows:
            field_rows[field] = idx
    if "building_name" not in field_rows:
        return stats

    micro_market_id = None if dry_run else db.ensure_micro_market(sheet_name.strip())
    name_row = rows[field_rows["building_name"]]
    photo_row_idx = field_rows.get("photo")

    # anchor column -> images sitting on (or just below) the photograph row
    images_by_col: Dict[int, List[Dict[str, Any]]] = {}
    for entry in image_entries:
        images_by_col.setdefault(entry["col"], []).append(entry)

    def cell(field: str, col: int):
        idx = field_rows.get(field)
        if idx is None:
            return None
        row = rows[idx]
        return row[col] if col < len(row) else None

    # building_id -> its options. A tower with three operators contributes
    # three options to one building, so they are written together at the end.
    pending: Dict[str, List[Dict[str, Any]]] = {}
    operators_seen: Dict[str, set] = {}

    for col in range(1, max(len(r) for r in rows)):
        building_name = _text(name_row[col] if col < len(name_row) else None)
        if not building_name:
            continue

        operator_name = None
        operator_brand = None
        # 'Wework - The Pavillion' / 'UV - HM Icon Square': the prefix is the operator
        split = re.split(r"\s+-\s+", building_name, maxsplit=1)
        if len(split) == 2 and len(split[0]) <= 24:
            operator_brand, building_name = split[0].strip(), split[1].strip()
            operator_name = (operator_map or {}).get(operator_brand, operator_brand)
            if operator_name == operator_brand:
                operator_brand = None   # nothing extra to preserve

        developer_name = _text(cell("developer", col))
        if dry_run:
            developer_id = operator_id = None
        else:
            developer_id = db.ensure_organisation(developer_name, "developer") if developer_name else None
            operator_id = db.ensure_organisation(operator_name, "operator") if operator_name else None

        latitude, longitude = _latlng(cell("location_map", col))
        oc_text = _norm(cell("oc", col))

        building_payload = {
            "name": building_name,
            "address": _text(cell("address", col)),
            "locality": _text(cell("address", col)),
            "micro_market_id": micro_market_id,
            "developer_id": developer_id,
            "operator_id": operator_id,
            "operator_brand": operator_brand,
            "supply_type": supply_type,
            "asset_type": "office",
            "structure": _text(cell("structure", col)),
            "total_size_sqft": _num(cell("total_size", col)),
            "total_size_basis": _text(cell("total_size", col)),
            "avg_floor_plate_sqft": _num(cell("avg_floor_plate", col)),
            "floor_plate_efficiency": _text(cell("floor_plate_efficiency", col)),
            "power_kva": _text(cell("power_kva", col)),
            "power_backup": _text(cell("power_backup", col)),
            "car_parking_ratio": _text(cell("parking_ratio", col)),
            "oc_available": True if oc_text.startswith("yes") else (False if oc_text.startswith("no") else None),
            "building_details": _text(cell("building_details", col)),
            "latitude": latitude,
            "longitude": longitude,
            "source_file": os.path.basename(sheet_name),
            "report_period": "2026",
        }
        if len(stats["sample"]) < 3:
            stats["sample"].append({
                "sheet": sheet_name,
                "building": building_name,
                "operator": operator_name,
                "operator_brand": operator_brand,
                "developer": developer_name,
                "supply_type": supply_type,
            })
        if dry_run:
            building_id = "dry:%s:%s" % (sheet_name, building_name.lower())
            if building_id not in pending:
                stats["buildings"] += 1
        else:
            building_id = db.upsert_building(building_payload)
            if building_id not in pending:
                stats["buildings"] += 1

        offered = cell("offered", col)
        offered_num = _num(offered)
        rent_value = _num(cell("rent", col))
        offering = classify_offering(offered_num)
        rate_unit = classify_rate(rent_value)
        looks_like_area = offering == "area"
        unit_note = offering_mismatch(offering, rate_unit)
        # Both ingest paths must write the same vocabulary into these columns;
        # the extraction side already normalises, so this one does too.
        timeline = schema.normalize_timeline(
            _text(cell("timeline", col)), "available") or None
        condition = schema.normalize_condition(
            _text(cell("status", col)), _text(cell("fitout", col))) or None

        # The managed sheets reuse the "Quoted Rental [INR/Sq.Ft./Month]" row for
        # per-seat pricing. Whether a rate is per seat follows from the unit the
        # offering is counted in, plus its own magnitude - a rate in the
        # thousands is never a square-foot rate.
        seat_priced = rate_unit == "seat"

        space = {
            "option_label": _text(rows[0][col] if col < len(rows[0]) else None),
            "floor_label": _text(cell("floor_offered", col)),
            "seats": int(offered_num) if offered_num is not None and not looks_like_area else None,
            "area_sqft": offered_num if looks_like_area else None,
            "condition": condition,
            "condition_detail": _text(cell("fitout", col)),
            "timeline": timeline,
            "occupancy": "occupied" if (timeline or "").lower() == "occupied"
                         else ("available" if (offered_num or 0) > 0 else "unknown"),
            "rent_psf": None if seat_priced else rent_value,
            "price_per_seat": rent_value if seat_priced else None,
            "cam_psf": _num(cell("cam", col)),
            "parking_charges": _text(cell("parking_charges", col)),
            "rental_escalation": _text(cell("escalation", col)),
            "deposit_months": _num(cell("deposit", col)),
            "lease_tenure_months": _num(cell("tenure", col)),
            "lock_in_months": _num(cell("lock_in", col)),
            "notice_months": _num(cell("notice", col)),
            "commercial_terms": _text(cell("commercial_terms", col)),
            "source_file": sheet_name,
            "operator_id": operator_id,
            "operator_brand": operator_brand,
            "notes": unit_note,
        }
        pending.setdefault(building_id, []).append(space)
        operators_seen.setdefault(building_id, set()).add(operator_id)
        stats["spaces"] += 1

        contact = {
            "name": _text(cell("contact_person", col)),
            "phone": _text(cell("contact_number", col)),
            "email": _text(cell("contact_email", col)),
        }
        if any(contact.values()):
            stats["contacts"] += (
                1 if dry_run else db.upsert_contacts([contact], building_id=building_id))

        if dry_run:
            stats["images"] += len(images_by_col.get(col, []))
        elif zip_handle is not None:
            stats["images"] += _upload_column_images(
                zip_handle, images_by_col.get(col, []), building_id, photo_row_idx, sheet_name)

    # Flush each building's options in one write, and clear the building-level
    # operator where the tower turns out to host more than one.
    if not dry_run:
        # spaces.operator_id arrives with migration 0003; drop it if the
        # database has not been migrated yet rather than failing the import.
        keeps_operator = db.has_column("spaces", "operator_id")
        for building_id, spaces in pending.items():
            if not keeps_operator:
                for space in spaces:
                    space.pop("operator_id", None)
                    space.pop("operator_brand", None)
            try:
                db.replace_spaces(building_id, spaces, source_file=sheet_name)
            except Exception:
                continue
            distinct = {op for op in operators_seen.get(building_id, set()) if op}
            if len(distinct) > 1:
                try:
                    db.client().table("buildings").update(
                        {"operator_id": None, "operator_brand": None}
                    ).eq("id", building_id).execute()
                except Exception:
                    pass

    return stats


def _upload_column_images(zip_handle: zipfile.ZipFile, entries: List[Dict[str, Any]],
                          building_id: str, photo_row_idx: Optional[int],
                          sheet_name: str) -> int:
    """Push one option column's photographs to Storage and record them."""
    if not entries:
        return 0
    # Nearest-to-the-photo-row first, so the perspective shot becomes primary.
    if photo_row_idx is not None:
        entries = sorted(entries, key=lambda e: abs(e["row"] - photo_row_idx))

    uploaded = 0
    for order, entry in enumerate(entries):
        try:
            data = zip_handle.read(entry["part"])
        except KeyError:
            continue
        ext = entry["ext"] if entry["ext"] in CONTENT_TYPES else ".png"
        path = "buildings/%s/%s-%d%s" % (building_id, db.slugify(sheet_name), order, ext)
        try:
            db.upload_bytes("building-images", path, data, CONTENT_TYPES.get(ext, "image/png"))
        except Exception:
            continue

        record = {
            "building_id": building_id,
            "storage_path": path,
            "kind": "perspective",
            "sort_order": order,
            "is_primary": order == 0,
            "bytes": len(data),
            "source_file": sheet_name,
        }
        try:
            db.client().table("building_images").insert(record).execute()
        except Exception:
            # A building that appears on two sheets already has its primary, and
            # the one-primary-per-building index rejects a second. Keep the image
            # rather than leaving it orphaned in storage with no row pointing at it.
            record["is_primary"] = False
            try:
                db.client().table("building_images").insert(record).execute()
            except Exception:
                continue
        uploaded += 1
    return uploaded


# ------------------------------------------------------------------ operators
def _import_operators(workbook, dry_run: bool = False) -> Dict[str, int]:
    """
    Reads the two reference sheets that describe the operators themselves.

    'Operators' is a grouped list - the operator name appears once and its
    extra contacts follow on unnamed rows - so the name is carried forward.
    'CBD-Managed Office List' says whether each operator does managed office,
    coworking, or both, which is what lets the same organisation supply two
    different supply_type categories.
    """
    stats = {"operators": 0, "contacts": 0}

    offerings: Dict[str, Dict[str, Any]] = {}
    sheet_name = next((n for n in workbook.sheetnames if _norm(n) == OFFERINGS_SHEET), None)
    if sheet_name:
        for row in workbook[sheet_name].iter_rows(min_row=2, values_only=True):
            name = _text(row[0] if row else None)
            if not name:
                continue
            # "CorporatEdge - UB City" describes one location of one operator
            base = re.split(r"\s+-\s+", name, maxsplit=1)[0].strip()
            offerings[_norm(base)] = {
                "offers_managed": _offering(row[1] if len(row) > 1 else None),
                "offers_coworking": _offering(row[2] if len(row) > 2 else None),
                "major_locations": _text(row[3] if len(row) > 3 else None),
            }

    sheet_name = next((n for n in workbook.sheetnames if _norm(n) == OPERATORS_SHEET), None)
    if not sheet_name:
        return stats

    current_name = None
    current_id = None
    for row in workbook[sheet_name].iter_rows(min_row=2, values_only=True):
        if not row or not any(row):
            continue
        name = _text(row[1] if len(row) > 1 else None)
        if name:
            current_name = name
            payload = dict(offerings.get(_norm(re.sub(r"\s*\(.*?\)", "", name).strip()), {}))
            status = _norm(row[5] if len(row) > 5 else None)
            if status:
                payload["is_active"] = status.startswith("yes")
            stats["operators"] += 1
            if dry_run:
                current_id = None
            else:
                current_id = db.ensure_organisation(current_name, "operator")
                if current_id and payload:
                    try:
                        db.client().table("organisations").update(
                            {k: v for k, v in payload.items() if v is not None}
                        ).eq("id", current_id).execute()
                    except Exception:
                        pass

        if not current_name:
            continue

        contact = {
            "name": _text(row[2] if len(row) > 2 else None),
            "phone": _text(row[3] if len(row) > 3 else None),
            "email": _text(row[4] if len(row) > 4 else None),
        }
        if any(contact.values()):
            stats["contacts"] += 1
            if not dry_run and current_id:
                try:
                    db.upsert_contacts([contact], organisation_id=current_id)
                except Exception:
                    pass

    return stats
