"""
Builds Master File rows from extracted buildings, including the derived
occupied-space rows.

Most landlords circulate only their vacant inventory. When the document also
states the building's total size we can recover what is let out:

    occupied balance = total building size - sum(available floor areas)

That balance is emitted as ONE aggregate row per building
(Available Floors = "Balance Floors", Timeline = "Occupied") rather than being
split across invented floor numbers.
"""
import re

from . import schema

BALANCE_LABEL = "Balance Floors"

# Ignore rounding noise: a balance must be both materially large and non-trivial.
MIN_BALANCE_SQFT = 1000
MIN_BALANCE_FRACTION = 0.01
FULL_STACK_GAP_FRACTION = 0.05

# Backstop only. A high balance is normal - a park with one suite on the
# market really is ~90% let - so this sits well above that, to catch the case
# where essentially nothing was listed yet an occupancy is still asserted.
# The real defence against a campus-level total is implausible_total(), which
# now refuses to pass an unreadable structure.
MAX_BALANCE_FRACTION = 0.97

# Sanity envelope for a Bengaluru office floor plate. A stated "total building
# size" that implies a plate outside this range is almost always a figure the
# model picked up from a neighbouring project on the same slide.
MAX_PLAUSIBLE_PLATE = 120000
MIN_PLAUSIBLE_PLATE = 500


def floors_from_structure(structure):
    """
    '2B + G + 9' -> 10 usable levels (9 upper + ground). None if unreadable.

    Annotations have to come off first. '3B(Parking) + G(Parking) + 13 Floors'
    used to count 16 levels, because the annotated basement no longer matched
    the basement branch and fell through to the generic digit grab - which then
    shrank the implied floor plate and let an implausible total past the guard.
    """
    if not structure:
        return None
    text = str(structure).upper()

    # "(2 Towers)" multiplies the stack; capture it before stripping brackets.
    towers = 1
    tower_match = re.search(r"(\d+)\s*TOWERS?", text)
    if tower_match:
        towers = max(1, int(tower_match.group(1)))
    elif re.search(r"TOWER\s+[A-Z]\s*(&|AND|\+)\s*[A-Z]", text):
        towers = 2

    text = re.sub(r"\([^)]*\)", " ", text)          # drop "(Parking)", "(Lobby)"
    text = re.sub(r"^\s*TOWERS?\s+[A-Z](\s*(&|AND|\+)\s*[A-Z])*\s*[-:]", " ", text)
    text = re.sub(r"\b(FLOORS?|LEVELS?|OFFICE|TOWERS?)\b", " ", text)

    upper = 0
    matched = False
    for part in re.split(r"\+", text):
        part = part.strip()
        if not part:
            continue
        if re.fullmatch(r"\d*\s*B(ASEMENTS?)?", part):   # basements are not leasable
            matched = True
            continue
        if re.fullmatch(r"G(F|ROUND)?", part):
            upper += 1
            matched = True
            continue
        number = re.search(r"\d+", part)
        if number:
            upper += int(number.group(0))
            matched = True
    return upper * towers if (matched and upper) else None


def implausible_total(total, structure):
    """
    Returns a reason string when a stated total cannot belong to this building.

    An unparseable structure is not a free pass. It used to return "" - no
    guard at all - which is how a campus-level total for RMZ Ecoworld Campus 20
    produced a derived "Occupied" row covering 98.5% of the building.
    """
    if not total:
        return ""
    floors = floors_from_structure(structure)
    if not floors:
        return ("building structure %r could not be read, so the stated total %s "
                "cannot be sanity-checked against a floor plate"
                % (str(structure or "")[:40], schema.sft(total)))
    plate = total / float(floors)
    if plate > MAX_PLAUSIBLE_PLATE:
        return ("stated total %s over %d levels implies a %s floor plate - likely "
                "picked up from another project on the same page"
                % (schema.sft(total), floors, schema.sft(plate)))
    if plate < MIN_PLAUSIBLE_PLATE:
        return ("stated total %s over %d levels implies only a %s floor plate"
                % (schema.sft(total), floors, schema.sft(plate)))
    return ""


def _space_rows(building, base, spaces):
    rows = []
    for space in spaces:
        area = schema.to_number(space.get("area_sqft"))
        occupancy = (space.get("occupancy") or "available").lower()
        condition = schema.normalize_condition(space.get("condition"), space.get("condition_detail"))
        detail = schema.clean_name(space.get("condition_detail"))
        row = dict(base)
        row.update({
            "Available  Floors": schema.normalize_floor(space.get("floor_label")),
            "Available - Area in Sft": schema.sft(area) if area else "",
            "Condition": condition or (detail[:180] if detail else ""),
            "Timeline": schema.normalize_timeline(space.get("timeline"), occupancy),
            "_area_sqft": area,
            "_occupancy": occupancy,
            "_condition_detail": detail,
            "_rent_psf": schema.to_number(space.get("rent_psf")),
            "_cam_psf": schema.to_number(space.get("cam_psf")),
            "_notes": schema.clean_name(space.get("notes")),
            "_derived": "",
        })
        rows.append(row)
    return rows


def build_building_rows(building, developer, source_meta):
    """Return (rows, diagnostics) for a single extracted building."""
    name = schema.clean_name(building.get("building_name"))
    locality = schema.clean_name(building.get("address_locality"))
    city = schema.clean_name(building.get("city")) or "Bengaluru"
    total = schema.to_number(building.get("total_building_size_sqft"))
    disclosure = (building.get("disclosure_mode") or "unknown").lower()
    asset_type = (building.get("asset_type") or "office").lower()
    txn_type = (building.get("transaction_type") or "lease").lower()

    # The folder names the landlord, not the asset. Blending it with the
    # address forced every building under "Park Square whitefield/" into
    # Whitefield, so it is only consulted when the address yields nothing.
    micromarket = schema.normalize_micromarket(locality, name)
    if micromarket in ("", "Others"):
        micromarket = schema.normalize_micromarket(
            locality, name, source_meta.get("folder", "")) or micromarket
    if not schema.is_bangalore(city, locality, name):
        micromarket = "Outside BLR"

    address = locality
    if city and city.lower() not in address.lower():
        address = (address + ", " + city).strip(", ") if address else city

    base = {
        "BLR - Categorization": micromarket,
        "Options": "",
        "Builder / Developer": developer,
        "Building Name": name,
        "Building Address / Location": address,
        "Building Structure": schema.normalize_structure(building.get("building_structure")),
        "Total Building Size [In Sq. Ft.]": schema.sft(total) if total else "",
        "Available  Floors": "",
        "Available - Area in Sft": "",
        "Condition": "",
        "Timeline": "",
        # meta (stripped before the Master File sheet is written)
        "_developer": developer,
        "_building": name,
        "_city": city,
        "_locality": locality,
        "_asset_type": asset_type,
        "_transaction_type": txn_type,
        "_total_sqft": total,
        "_total_basis": schema.clean_name(building.get("total_building_size_basis")),
        "_floor_plate": schema.to_number(building.get("typical_floor_plate_sqft")),
        "_disclosure": disclosure,
        "_evidence": schema.clean_name(building.get("evidence")),
        "_source_file": source_meta.get("rel_path", ""),
        "_source_kind": source_meta.get("kind", ""),
        "_period": source_meta.get("period", ""),
        "_area_sqft": None,
        "_occupancy": "",
        "_derived": "",
        "_condition_detail": "",
        "_rent_psf": None,
        "_cam_psf": None,
        "_notes": "",
    }

    spaces = building.get("spaces") or []
    rows = _space_rows(building, base, spaces)

    stated_available = schema.to_number(building.get("total_available_sqft"))
    available_sum = sum(r["_area_sqft"] or 0 for r in rows if r["_occupancy"] == "available")
    occupied_sum = sum(r["_area_sqft"] or 0 for r in rows if r["_occupancy"] == "occupied")
    # Floors of unclear status are still floors we have accounted for; excluding
    # them would inflate the derived balance.
    unknown_sum = sum(r["_area_sqft"] or 0 for r in rows
                      if r["_occupancy"] not in ("available", "occupied"))

    # A building whose availability is only given as one lump figure still deserves a row.
    if not rows and stated_available:
        lump = dict(base)
        lump.update({
            "Available  Floors": "",
            "Available - Area in Sft": schema.sft(stated_available),
            "Timeline": "Immediate",
            "_area_sqft": stated_available,
            "_occupancy": "available",
        })
        rows.append(lump)
        available_sum = stated_available

    # Nothing at all: keep the building on the sheet as a known asset with blank inventory.
    if not rows:
        placeholder = dict(base)
        placeholder["_occupancy"] = "unknown"
        rows.append(placeholder)

    estimated = bool(building.get("total_size_estimated"))
    diagnostics = {
        "developer": developer,
        "building": name,
        "source_file": source_meta.get("rel_path", ""),
        "total_sqft": total,
        "total_estimated": estimated,
        "available_sum": available_sum,
        "occupied_listed": occupied_sum,
        "stated_available": stated_available,
        "disclosure": disclosure,
        "balance_sqft": None,
        "balance_emitted": False,
        "issue": "",
    }

    if not total:
        diagnostics["issue"] = "no total building size stated - occupied space cannot be derived"
        return rows, diagnostics

    doubt = implausible_total(total, building.get("building_structure"))
    if doubt:
        diagnostics["issue"] = doubt + " - balance row suppressed"
        return rows, diagnostics

    accounted = available_sum + occupied_sum + unknown_sum
    if stated_available and not available_sum:
        accounted = stated_available + occupied_sum + unknown_sum
        diagnostics["available_sum"] = stated_available

    # Without a single measurable area we have no evidence about what is let.
    # Deriving here would claim the whole building is occupied purely because
    # the document gave no floor areas.
    if accounted <= 0:
        diagnostics["issue"] = ("building size known but no floor areas listed - "
                                "occupied space cannot be derived from an empty inventory")
        return rows, diagnostics

    balance = total - accounted
    diagnostics["balance_sqft"] = balance

    if accounted > total * 1.02:
        diagnostics["issue"] = ("listed area (%s) exceeds stated building size (%s) - "
                                "no balance row emitted" % (int(accounted), int(total)))
        return rows, diagnostics

    threshold = max(MIN_BALANCE_SQFT, total * MIN_BALANCE_FRACTION)
    if disclosure == "full_stack":
        threshold = max(threshold, total * FULL_STACK_GAP_FRACTION)

    if balance >= total * MAX_BALANCE_FRACTION:
        diagnostics["issue"] = (
            "derived balance %s is %.0f%% of the stated total - the total most "
            "likely covers more than the listed floors; no balance row emitted"
            % (schema.sft(balance), 100 * balance / total))
        return rows, diagnostics

    if balance >= threshold:
        basis = "estimated total" if estimated else "stated total"
        balance_row = dict(base)
        balance_row.update({
            "Available  Floors": BALANCE_LABEL + (" (est.)" if estimated else ""),
            "Available - Area in Sft": schema.sft(balance),
            "Condition": "-",
            "Timeline": "Occupied",
            "_area_sqft": balance,
            "_occupancy": "occupied",
            "_derived": "Derived: %s building size (%s) minus listed space (%s)"
                        % (basis, schema.sft(total), schema.sft(accounted)),
        })
        rows.append(balance_row)
        diagnostics["balance_emitted"] = True

    return rows, diagnostics


def strip_meta(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}
