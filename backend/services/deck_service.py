"""
Prompt -> shortlist -> PowerPoint.

The user types a requirement in plain English ("30,000 sft warm shell on ORR,
ready to move"). An LLM turns that into structured filters, those filters query
Supabase, and the resulting shortlist is rendered through the existing
`options format.pptx` template.

Everything the deck says comes from the database. The LLM chooses *what* to
show and writes the narrative copy; it is never the source of a number.
"""
import json
import os
import shutil
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import config
import db

from services import categories

from ai_client import AIClient  # from ../../LLM

MICRO_MARKET_HINTS = {
    "orr": "ORR", "outer ring road": "ORR",
    "whitefield": "WF", "wf": "WF",
    "cbd": "CBD", "central business district": "CBD",
    "north": "North-BLR", "hebbal": "North-BLR", "manyata": "North-BLR",
    "ecity": "E-City", "e-city": "E-City", "electronic city": "E-City",
    "indiranagar": "Indiranagar", "domlur": "Indiranagar",
    "koramangala": "KRM", "krm": "KRM",
    "hsr": "HSR Layout",
    "bannerghatta": "BG Road", "bg road": "BG Road",
    "jp nagar": "JP-Nagar", "jayanagar": "Jayanagar",
    "kanakapura": "Kanakapura Rd", "btm": "BTM",
}

PARSE_PROMPT = """Turn this commercial real estate requirement into JSON filters.

Requirement: "{query}"

Return ONLY a JSON object with these keys (use null when the requirement does not say):
  micro_markets   : array of codes from [CBD, ORR, WF, North-BLR, E-City, Indiranagar,
                    KRM, HSR Layout, BG Road, JP-Nagar, Jayanagar, Kanakapura Rd, BTM]
  supply_type     : "conventional" | "managed" | "sale" | null
                    ("managed" covers managed and co-working stock, which is
                     one listing - use it for any flex/seat requirement)
  min_area_sqft   : number or null
  max_area_sqft   : number or null
  seats           : the headcount they asked for, as a number, else null
  min_seats       : number or null
  max_seats       : number or null
  max_rent_psf    : number or null
  condition       : one of "Bare Shell","Warm Shell","Pre - Furnished","Fully Furnished","Managed Office" or null
  developers      : array of landlord names mentioned, else []
  ready_now       : true if they need immediate/ready-to-move space, else null
  limit           : only if they asked for a specific number of options
                    ("show me 5"), otherwise null - every option that fits is
                    shown and the operator trims the list by hand
  title           : a short deck title for this requirement
"""


# A safety ceiling, not a shortlist length. Nothing should ever return more
# than this many options; a market has nowhere near that much live stock.
MAX_OPTIONS = 200

# How far below the requirement an option may fall and still be worth showing.
# At 0.85 a 150-seat brief still surfaces a 128-seat centre - close enough that
# a client might take it - but not a 105-seat one. Set lower, the near-miss tail
# grew long enough to bury the options that actually fit.
NEAR_MISS_FLOOR = 0.85


def requirement_size(criteria: Dict[str, Any]):
    """
    What the brief actually asks for, as (amount, unit).

    The parser is inconsistent about which key it fills - a seat count arrives
    as `seats` or as `min_seats` depending on how the requirement was phrased -
    and reading only one of them meant a brief for 150 seats carried no size at
    all. With no size, nothing was ranked by fit and a 70-seat centre sorted
    above a 167-seat one.
    """
    for key in ("seats", "min_seats"):
        value = criteria.get(key)
        if value:
            try:
                return float(value), "seats"
            except (TypeError, ValueError):
                pass
    for key in ("area_sqft", "min_area_sqft"):
        value = criteria.get(key)
        if value:
            try:
                return float(value), "area"
            except (TypeError, ValueError):
                pass
    return None, None


def parse_requirement(query: str) -> Dict[str, Any]:
    """LLM-parse the prompt, with a keyword fallback when no API key is live."""
    ai = AIClient()
    criteria: Dict[str, Any] = {}
    if ai.get_active_provider() != "none":
        try:
            raw = ai.generate_text(PARSE_PROMPT.format(query=query))
            cleaned = raw.replace("```json", "").replace("```", "").strip()
            criteria = json.loads(cleaned)
        except Exception:
            criteria = {}

    if not criteria:
        criteria = _fallback_parse(query)

    criteria.setdefault("title", "Office Space Options")
    return _apply_seat_rule(reconcile(criteria, query))


# A headcount, an area, and an explicit request for N options. These are read
# from the requirement directly rather than taken from the model, because the
# model is not reliable about them: asked the same question three times it
# returned seats=150 twice and, once, no headcount at all plus an invented
# limit of 6 - which is precisely the truncated, badly ranked shortlist this
# was reported as.
SEATS_RE = re.compile(
    r"(\d[\d,]*)\s*(?:\w+\s+){0,2}?"
    r"(?:seats?|desks?|pax|people|headcount|workstations?)", re.I)
AREA_RE = re.compile(
    r"(\d[\d,.]*)\s*(k\b)?\s*(?:sq\.?\s*ft|sft|sqft|square\s*feet)", re.I)
COUNT_RE = re.compile(
    r"(?:top|show|give|list|send)\s+(?:me\s+)?(\d+)\b"
    r"|\b(\d+)\s+options?\b", re.I)


def _number(text: str) -> Optional[float]:
    try:
        return float(str(text).replace(",", ""))
    except (TypeError, ValueError):
        return None


def reconcile(criteria: Dict[str, Any], query: str) -> Dict[str, Any]:
    """
    Let the requirement text override the model on anything countable.

    The model is good at the parts that need judgement - which micro-market a
    place name belongs to, what condition is being described, what the client
    is really after. It is unreliable at copying a number out of a sentence,
    and a dropped headcount silently disables fit ranking entirely.
    """
    text = query or ""

    match = SEATS_RE.search(text)
    if match:
        value = _number(match.group(1))
        if value:
            criteria["seats"] = value

    match = AREA_RE.search(text)
    if match:
        value = _number(match.group(1))
        if value:
            if match.group(2) and value < 1000:      # "30k sft"
                value *= 1000
            criteria["area_sqft"] = value

    # A count is honoured only when the requirement asks for one in so many
    # words. Left to itself the model supplies one on every request.
    match = COUNT_RE.search(text)
    criteria["limit"] = _number(match.group(1) or match.group(2)) if match else None
    if criteria["limit"]:
        criteria["limit"] = max(1, min(int(criteria["limit"]), MAX_OPTIONS))
    return criteria


def _apply_seat_rule(criteria: Dict[str, Any]) -> Dict[str, Any]:
    """
    Decide managed vs co-working from the headcount, not from the listing.

    The stock is the same either way, so this only ever changes what the
    proposal calls the product. A brief with no headcount gets no product
    label at all rather than a guessed one.
    """
    criteria["supply_type"] = categories.canonical_supply_type(criteria.get("supply_type"))

    seats = criteria.get("seats") or criteria.get("min_seats")
    product = categories.product_for_seats(seats)
    if product:
        criteria["seats"] = seats
        criteria["product"] = product
        criteria["product_label"] = categories.product_label(product)
        criteria["product_note"] = categories.describe_product(product, seats)
        # A seat requirement is flex stock whatever the parser said.
        criteria["supply_type"] = "managed"
    return criteria


def _fallback_parse(query: str) -> Dict[str, Any]:
    low = (query or "").lower()
    markets = sorted({code for hint, code in MICRO_MARKET_HINTS.items() if hint in low})

    area = None
    match = re.search(r"([\d,]+(?:\.\d+)?)\s*(?:k\b|sq\s*ft|sft|sqft)", low)
    if match:
        value = float(match.group(1).replace(",", ""))
        if "k" in match.group(0) and value < 1000:
            value *= 1000
        area = value

    seats = None
    seat_match = re.search(r"([\d,]+)\s*(?:seats?|desks?|pax)", low)
    if seat_match:
        seats = float(seat_match.group(1).replace(",", ""))

    condition = None
    for label, pattern in [("Warm Shell", r"warm shell"), ("Bare Shell", r"bare shell|core"),
                           ("Fully Furnished", r"furnish|plug"), ("Managed Office", r"managed|coworking|flex")]:
        if re.search(pattern, low):
            condition = label
            break

    return {
        "micro_markets": markets,
        "supply_type": "managed" if re.search(r"managed|coworking|seats?|flex", low) else None,
        "area_sqft": area,
        "min_area_sqft": area * 0.8 if area else None,
        "max_area_sqft": area * 1.6 if area else None,
        "seats": seats,
        "min_seats": seats * 0.8 if seats else None,
        "max_seats": seats * 1.6 if seats else None,
        "max_rent_psf": None,
        "condition": condition,
        "developers": [],
        "ready_now": bool(re.search(r"immediate|ready|now|asap", low)),
        "limit": 6,
        "title": query.strip()[:70] or "Office Space Options",
    }


def shortlist(criteria: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Query Supabase for buildings whose *available* space fits the brief."""
    sb = db.client()

    query = sb.table("buildings").select(
        "id, name, address, locality, city, structure, total_size_sqft, "
        "avg_floor_plate_sqft, floor_plate_efficiency, power_kva, power_backup, "
        "car_parking_ratio, oc_available, building_details, latitude, longitude, "
        "supply_type, report_period, "
        "micro_markets(code, name), "
        "developer:organisations!buildings_developer_id_fkey(name), "
        "operator:organisations!buildings_operator_id_fkey(name), "
        "spaces(*), building_images(storage_path, is_primary, sort_order, kind), "
        "contacts(name, designation, phone, email)"
    )
    stored = categories.stored_supply_types(criteria.get("supply_type"))
    if stored:
        query = query.in_("supply_type", stored)

    rows = query.limit(600).execute().data or []

    required, unit = requirement_size(criteria)
    codes = set(criteria.get("micro_markets") or [])
    max_rent = criteria.get("max_rent_psf")
    condition = (criteria.get("condition") or "").lower()
    developers = [d.lower() for d in (criteria.get("developers") or [])]
    ready_now = criteria.get("ready_now")

    scored = []
    for row in rows:
        market = (row.get("micro_markets") or {}).get("code")
        if codes and market not in codes:
            continue

        # Who the client is dealing with. For managed and co-working space that
        # is the operator running the centre - naming the developer instead
        # billed 315Work Avenue's KRM 1 as "Sattva Group", which is the owner
        # of the tower and not a party to the deal.
        developer = (row.get("developer") or {}).get("name") or ""
        operator = ((row.get("operator") or {}).get("name")
                    or row.get("operator_brand") or "")
        if categories.canonical_supply_type(row.get("supply_type")) == "managed":
            landlord = operator or developer
        else:
            landlord = developer or operator
        if developers and not any(d in landlord.lower() for d in developers):
            continue

        vacant = [s for s in (row.get("spaces") or []) if s.get("occupancy") == "available"]
        if not vacant:
            continue
        if ready_now:
            vacant = [s for s in vacant if (s.get("timeline") or "").lower() == "immediate"] or vacant
        if condition:
            matching = [s for s in vacant if condition in (s.get("condition") or "").lower()]
            vacant = matching or vacant

        area = sum(s.get("area_sqft") or 0 for s in vacant)
        seats = sum(s.get("seats") or 0 for s in vacant)

        # Classify against the requirement rather than filtering on it. An
        # option that is slightly short is still worth putting in front of a
        # client - it is their call, not the filter's - but it has to be
        # labelled, and it must not outrank one that actually fits.
        fit, shortfall, surplus = "unknown", 0.0, 0.0
        if required:
            have = seats if unit == "seats" else area
            if have <= 0:
                fit = "unknown"
            elif have >= required:
                fit, surplus = "meets", have - required
            elif have >= required * NEAR_MISS_FLOOR:
                fit, shortfall = "short", required - have
            else:
                continue   # too small to serve this brief at all

        rents = [s["rent_psf"] for s in vacant if s.get("rent_psf")]
        rent = min(rents) if rents else None
        seat_prices = [s["price_per_seat"] for s in vacant if s.get("price_per_seat")]
        seat_price = min(seat_prices) if seat_prices else None
        if max_rent and rent and rent > max_rent:
            continue

        # Readiness and a photograph decide ties; they never promote an option
        # over one that fits the requirement better.
        quality = 0.0
        if any((s.get("timeline") or "").lower() == "immediate" for s in vacant):
            quality += 1.5
        if row.get("building_images"):
            quality += 1.0
        if row.get("total_size_sqft"):
            quality += 0.3

        row["_fit"] = fit
        row["_shortfall"] = shortfall
        row["_surplus"] = surplus
        row["_quality"] = quality

        row["_vacant"] = vacant
        row["_available_sqft"] = area
        row["_available_seats"] = seats
        row["_rent"] = rent
        row["_seat_price"] = seat_price
        row["_landlord"] = landlord
        row["_operator"] = operator
        row["_developer"] = developer
        row["_micro_market"] = market
        scored.append(row)

    # Options that meet the requirement come first, tightest fit leading, so an
    # exact match is not buried under a centre five times the size. Near misses
    # follow, smallest gap first. Readiness and photographs only break ties.
    order = {"meets": 0, "short": 1, "unknown": 2}
    scored.sort(key=lambda r: (
        order.get(r["_fit"], 3),
        r["_surplus"] if r["_fit"] == "meets" else r["_shortfall"],
        -r["_quality"],
        r["name"] or "",
    ))

    # Every match is returned. The operator removes what they do not want, on a
    # screen that shows them all - which is a judgement the filter cannot make
    # and should not have been making by truncating to six.
    limit = criteria.get("limit") or MAX_OPTIONS
    return scored[:limit]


def _fmt_int(value) -> str:
    """A number for the client, or nothing. Zero is absence, not a figure."""
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return ""
    return "{:,}".format(number) if number else ""


def _fmt_sqft(value) -> str:
    """
    An area in Indian digit grouping, or nothing.

    Zero returns empty rather than "0 Sq. Ft.": a seat-based option has no
    area, and printing a zero told a client the suite was nothing at all.
    """
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return ""
    if not number:
        return ""
    digits = str(number)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups) + "," + tail
    return digits + " Sq. Ft."


def to_option_records(buildings: List[Dict[str, Any]],
                     criteria: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Shape database rows into the flat dicts the PPT and Excel writers expect.

    `criteria` supplies the product name - managed or co-working - which is a
    property of the requirement rather than of the building, so it is stamped
    onto every option in the proposal rather than read back off each record.
    """
    criteria = criteria or {}
    requirement_product = criteria.get("product")
    records = []
    for row in buildings:
        vacant = row.get("_vacant") or []
        floors = ", ".join(sorted({s.get("floor_label") or "" for s in vacant if s.get("floor_label")}))
        conditions = sorted({s.get("condition") for s in vacant if s.get("condition")})
        timelines = sorted({s.get("timeline") for s in vacant if s.get("timeline")})
        first = vacant[0] if vacant else {}
        contacts = row.get("contacts") or []
        contact = contacts[0] if contacts else {}

        images = sorted(row.get("building_images") or [],
                        key=lambda i: (not i.get("is_primary"), i.get("sort_order") or 0))
        image_url = ""
        if images:
            try:
                image_url = db.public_url(config.BUCKET_IMAGES, images[0]["storage_path"])
            except Exception:
                image_url = ""

        records.append({
            "_product_label": categories.product_label(
                requirement_product
                or categories.canonical_supply_type(row.get("supply_type"))),
            "building_name": row.get("name"),
            "address_location": row.get("address") or row.get("locality") or "",
            "micromarket_category": row.get("_micro_market") or "",
            "developer_landlord": row.get("_landlord") or "",
            "building_structure": row.get("structure") or "",
            "total_building_size_sqft": _fmt_sqft(row.get("total_size_sqft")),
            "average_floor_plate_sqft": _fmt_sqft(row.get("avg_floor_plate_sqft")),
            "floor_plate_efficiency": row.get("floor_plate_efficiency") or "",
            "power_kva": row.get("power_kva") or "",
            "power_backup": row.get("power_backup") or "",
            "building_details": row.get("building_details") or "",
            "available_inventory_sqft": _fmt_sqft(row.get("_available_sqft")) or "",
            "offered_seats": row.get("_available_seats") or "",
            "floor_offered": floors or "Multiple floors",
            "fitout_details": ", ".join(conditions) or "",
            "status": ", ".join(conditions) or "",
            "timeline": ", ".join(timelines) or "Immediate",
            # Managed stock quotes a seat rate; conventional quotes per sq ft.
            "quoted_rental_sqft_pm": (
                ("INR %s / seat / month" % _fmt_int(row.get("_seat_price")))
                if row.get("_seat_price") else (row.get("_rent") or "")
            ),
            "price_per_seat": row.get("_seat_price") or "",
            "cam_charges_sqft_pm": first.get("cam_psf") or "",
            "car_parking_ratio": row.get("car_parking_ratio") or "",
            "car_parking_charges": first.get("parking_charges") or "",
            "rental_escalation": first.get("rental_escalation") or "",
            "security_deposit_months": first.get("deposit_months") or "",
            "lease_tenure_months": first.get("lease_tenure_months") or "",
            "lock_in_period_months": first.get("lock_in_months") or "",
            "notice_period_months": first.get("notice_months") or "",
            "commercial_terms": first.get("commercial_terms") or "",
            "occupancy_certificate": "Yes" if row.get("oc_available") else "",
            "location_map": ("%s, %s" % (row.get("latitude"), row.get("longitude"))
                             if row.get("latitude") else ""),
            "contact_person": contact.get("name") or "",
            "contact_number": contact.get("phone") or "",
            "official_email": contact.get("email") or "",
            "building_perspective_photo": image_url,
            "_image_url": image_url,
            "_building_id": row.get("id"),
        })
    return records


OUTPUT_FORMATS = ("pptx", "xlsx")


def generate(query: str, client_name: str = "Valued Client",
             template_name: Optional[str] = None,
             deck_id: Optional[str] = None,
             building_ids: Optional[List[str]] = None,
             output_format: str = "pptx") -> Dict[str, Any]:
    """
    Full path: prompt -> criteria -> shortlist -> .pptx or .xlsx on disk.

    `building_ids` pins the output to an exact set of buildings, in that order -
    used when the operator has reviewed the model's shortlist and adjusted it.
    Without it the shortlist is recomputed from the prompt.

    Both formats are rendered from the same option records, so the sheet and
    the deck can never disagree about a number.
    """
    output_format = (output_format or "pptx").lower()
    if output_format not in OUTPUT_FORMATS:
        raise ValueError("Unknown output format: %s" % output_format)

    criteria = parse_requirement(query)
    buildings = shortlist(criteria)

    if building_ids:
        wanted = list(building_ids)
        by_id = {b["id"]: b for b in buildings}
        missing = [bid for bid in wanted if bid not in by_id]
        if missing:
            # A pinned building that fell outside the filters is still fetched,
            # so an operator override is never silently dropped.
            extra = shortlist({**criteria, "micro_markets": [], "limit": 500})
            by_id.update({b["id"]: b for b in extra if b["id"] in missing})
        buildings = [by_id[bid] for bid in wanted if bid in by_id]

    if not buildings:
        raise ValueError(
            "No buildings in the database match that requirement. "
            "Try widening the area or micro-market, or import more supply first.")

    records = to_option_records(buildings, criteria)

    safe_title = re.sub(r"[^A-Za-z0-9]+", "_", criteria.get("title") or "Options").strip("_")[:60]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = "%s_%s.%s" % (safe_title, stamp, output_format)

    if output_format == "xlsx":
        from services import deck_excel
        out_path = deck_excel.build(
            records, criteria, client_name, query,
            os.path.join(config.DECK_DIR, filename))
        return {
            "path": out_path,
            "filename": filename,
            "format": "xlsx",
            "criteria": criteria,
            "building_ids": [b["id"] for b in buildings],
            "options": len(records),
        }

    from ppt_generator import PPTGenerator
    generator = PPTGenerator(template_name=template_name or "options format.pptx")

    # generate_presentation writes into LLM/generated_decks and returns that path.
    produced = generator.generate_presentation(
        matched_records=records,
        summary_data=summarise(records),
        client_name=client_name,
        requirement_summary=criteria.get("title") or query,
        output_filename=filename,
    )

    # Keep every deck this service made under the backend's own work directory.
    out_path = os.path.join(config.DECK_DIR, filename)
    try:
        if produced and os.path.abspath(produced) != os.path.abspath(out_path):
            shutil.copy2(produced, out_path)
        elif not os.path.exists(out_path):
            out_path = produced
    except Exception:
        out_path = produced

    return {
        "path": out_path,
        "filename": filename,
        "format": "pptx",
        "criteria": criteria,
        "building_ids": [b["id"] for b in buildings],
        "options": len(records),
    }


def summarise(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Executive-summary figures for the deck's cover slide.

    Computed here rather than through RequirementEngine.generate_summary, whose
    constructor loads a CSV this service does not use - the database is the
    only source now.
    """
    def as_number(value):
        try:
            return float(re.sub(r"[^\d.]", "", str(value)) or 0)
        except ValueError:
            return 0.0

    areas = [as_number(r.get("available_inventory_sqft")) for r in records]
    rents = [as_number(r.get("quoted_rental_sqft_pm")) for r in records]
    live_rents = [r for r in rents if r > 0]

    return {
        "count": len(records),
        "total_area": int(sum(areas)),
        "avg_rent": round(sum(live_rents) / len(live_rents), 2) if live_rents else 0,
        "micromarkets_covered": sorted({r.get("micromarket_category") for r in records if r.get("micromarket_category")}),
        "developers_covered": sorted({r.get("developer_landlord") for r in records if r.get("developer_landlord")}),
    }
