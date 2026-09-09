"""
Prompt + response-schema definitions for the two LLM passes.

Pass 1 reads a whole source document and returns every building it describes.
Pass 2 re-reads the same document to fill specific gaps pass 1 left null
(most importantly the total building size, which is what lets us derive
occupied space for landlords who only circulate their vacant inventory).
"""

# Versioned separately so tuning one pass does not invalidate the other's cache.
PROMPT_VERSION_P1 = "v6"
PROMPT_VERSION_P2 = "v4"

SYSTEM_PROMPT = """You are a commercial real estate data analyst working on Bengaluru (Bangalore) office supply.
You read landlord availability reports, pitch decks, rent cards and inventory sheets, and you transcribe them
into structured records.

ABSOLUTE RULES:
1. Transcribe, never invent. If the document does not state a value, return null for it.
2. Never estimate an area, a floor number, a rent or a date that is not in the document.
3. Areas are always in square feet (sft). Convert stated units before returning:
   "1.1 Mn Sq ft" -> 1100000, "0.66 Mn" -> 660000, "1,26,408 Sqft" -> 126408, "4.5 lakh sft" -> 450000.
   Return areas as plain integers with no separators, commas or unit suffix.
4. A "building" is one tower / block / standalone asset. A tech park with named blocks
   (e.g. Bagmane WTC Block A, Block B) produces one record PER BLOCK, not one for the park.
5. Read tables, floor-stacking charts and slide layouts carefully. Availability charts often place
   the floor label in one column and its area in another - keep them correctly paired.
6. VACANT IS NOT THE SAME AS LISTED. Many of these decks print a building's ENTIRE floor stack -
   every floor and its area - and then indicate which of those floors are actually on offer.
   That indication is often VISUAL and absent from the text layer: colour fill or shading on
   certain rows, a coloured legend swatch ("Available", "Vacant", "Let"), a tick or asterisk,
   bold text, or a separate status column.
   Look at the rendered page and decide per floor. A floor listed in the stack is NOT available
   unless the document indicates it is.
7. DO NOT read a fit-out abbreviation as an availability marker. "(WS)", "Warm Shell",
   "(BS)", "Bare Shell", "(FF)" and the like describe the CONDITION of that space and say
   nothing about whether it is vacant. A floor can be warm shell and fully occupied. When a
   page uses colour to mark availability, colour is the only availability signal on it -
   record the fit-out abbreviation in `condition` and ignore it when setting `occupancy`.
"""

EXTRACTION_INSTRUCTIONS = """Extract every commercial property described in the attached document from
developer/landlord "{developer}" (source file: "{filename}").

Return one record per building/tower/block. For each building capture its floor-by-floor space list.

FIELD GUIDANCE:

- building_name: the marketed name exactly as printed (e.g. "Bagmane World Technology Center - Block 6").
- address_locality: the locality/address text as printed (e.g. "ORR / Mahadevapura", "Vittal Mallya Road").
  Do not normalise or reword it.
- city: the city the asset is in. Most are Bengaluru, but some decks include Pune, Mumbai, Noida,
  Hyderabad or Chennai assets - report the real city.
- asset_type: one of office, retail, industrial, warehouse, land, residential, mixed.
- transaction_type: one of lease, sale, managed_office, mixed. Use "sale" only when the document
  explicitly markets the space for outright sale/strata purchase.
- building_structure: the stated structure string, e.g. "3B+G+14", "2B + G + 19", "G + 4".
- total_building_size_sqft: the TOTAL leasable/chargeable area of this building.
  This field is what lets us work out how much of the building is already let, so work at it.
    1. Look for it stated outright - labels vary: "Project Size", "Total Building Size",
       "Building Area", "Total Area", "Capacity", "Development Size", "Total Chargeable Area".
    2. Sanity-check that the figure belongs to THIS building, not a neighbouring project on the
       same page: the total divided by the number of levels above ground must give a believable
       floor plate (roughly 5,000-90,000 sft for a Bengaluru office tower). If the arithmetic is
       absurd, you have grabbed another project's number - return null instead.
    3. ONLY if no total is stated anywhere, you may reconstruct one and set
       total_size_estimated=true, showing the arithmetic in total_building_size_basis:
         (a) stated typical floor plate x levels above ground, or
         (b) available area / number of floors it covers = implied plate, x levels above ground.
       Prefer (a). If neither is possible, return null - never guess a round number.
  Do NOT simply sum the vacant floors: that is the available area, not the building size.
- total_size_estimated: true only when you reconstructed the total under rule 3, else false.
- total_building_size_basis: short quote of the label you took the number from, or the
  arithmetic you used if you reconstructed it. Null if there is no total.
- typical_floor_plate_sqft: stated typical/average floor plate. Null if absent.
- total_available_sqft: total vacant area being offered in this building, if the document states a
  single figure for it (e.g. "Available: 1,05,000 sft", or the upper bound of an
  "Availability Range 7,020 sft to 4,67,470 sft" -> 467470). Null if not stated.
- disclosure_mode: how complete the floor list is.
    "full_stack"      -> the document lists the whole floor stack (whether or not it labels each
                         floor's status). This is the right answer whenever a floor table adds up
                         to roughly the total building size.
    "available_only"  -> the document lists ONLY the vacant/offered space (most availability reports).
    "unknown"         -> cannot tell.
- spaces: one entry per floor or per offered unit that the document names.
    floor_label: as printed, normalised lightly to the house style: "GF", "1F", "5F", "12F",
                 "Full Building (3B+G+10)", "2F & 3F", "Mezzanine", "Terrace".
                 Null if the document gives an area with no floor.
    area_sqft: integer sft for THAT entry.
    condition: one of "Bare Shell", "Warm Shell", "Pre - Furnished", "Fully Furnished",
               "Managed Office", "BTS", or null. Map synonyms: plug-and-play/plug & play -> Fully Furnished;
               core & shell -> Bare Shell; built-to-suit -> BTS.
    condition_detail: any extra fit-out description (workstation counts, meeting-room counts, etc.), else null.
    timeline: "Immediate" if ready/ready-to-occupy/available now; "Occupied" if the document says the
              floor is leased/occupied/let out; otherwise the stated availability date as printed
              ("Q3 2026", "Dec 2026", "Mar-27"). Null if not stated.
    occupancy: THE MOST IMPORTANT FIELD ON THIS ROW. Decide it per floor from what the page shows:
               "available" - the document indicates this specific floor is on offer: its text or
                             row is in the legend's "available" colour, it is highlighted/ticked, it
                             sits under an "Available" heading, or the whole table is a
                             vacancy-only list. A fit-out marker such as "(WS)" is NOT such an
                             indication.
               "occupied"  - the floor appears in the stack but is not indicated as on offer, or is
                             marked leased / occupied / let / not available.
               "unknown"   - the floor is listed and you genuinely cannot tell which it is.
               Never default a whole floor stack to "available". If a table lists every floor of the
               building and marks only some of them, the rest are "occupied". Use "unknown" rather
               than guessing "available" when the indication is ambiguous.
    rent_psf: stated quoted rent per sft per month as a number, else null.
    cam_psf: stated CAM per sft per month as a number, else null.
    notes: anything else relevant to this specific space, else null.
- contacts: leasing contacts printed in the document (name, designation, phone, email). Empty list if none.
- evidence: a short phrase naming where in the document this building's numbers came from,
  e.g. "p.12 availability table" or "slide 4 floor stacking chart".

If the document contains no leasable property data at all (pure marketing, a location map, a
covering page), return an empty buildings list and explain why in document_note.
"""

GAPFILL_INSTRUCTIONS = """Re-read the attached document from landlord "{developer}" (file "{filename}").

An earlier pass extracted these buildings but could not find some fields. For EACH building below,
search the whole document again - including headline stats, fact boxes, footers, floor-plate tables,
site-plan callouts and the fine print - and supply only the fields listed as missing.

BUILDINGS AND THEIR MISSING FIELDS:
{gap_list}

Rules for every field EXCEPT total_building_size_sqft:
- Only return a value you can point to in the document. If it genuinely is not there, return null
  and say so in reasoning. A null is far more useful to us than a guess.

Rules for total_building_size_sqft (the most important field - it is what lets us work out how much
of the building is already let):
- FIRST look for it stated outright: "Project Size", "Total Building Size", "Building Area",
  "Total Area", "Development Size", "Capacity", "Total Chargeable Area". If you find one,
  return it with derived=false and quote the label in total_building_size_basis.
- IMPORTANT: make sure the figure actually belongs to THIS building. These decks put several
  projects on one page. Sanity-check it against the building's own structure: a stated total
  divided by the number of levels above ground must give a believable floor plate
  (roughly 5,000-90,000 sft for a Bengaluru office tower). If the arithmetic gives something
  absurd, you have grabbed a neighbouring project's number - return null instead.
- ONLY IF no total is stated anywhere, you may RECONSTRUCT one, and you must then set
  derived=true and show the arithmetic in reasoning. Valid reconstructions:
    (a) stated typical floor plate x number of levels above ground from the structure
        (e.g. plate 25,000 sft, structure 3B+G+14 -> 15 levels -> 3,75,000 sft)
    (b) the available area divided by the number of floors it covers, giving an implied
        plate, then multiplied by the total levels above ground
        (e.g. "2F to 7F = 1,10,000 sft" -> 6 floors -> 18,333 sft plate;
         structure 3B+G+7 -> 8 levels -> 1,46,667 sft)
  Use (a) in preference to (b). If neither is possible, return null - do not guess a round number.
- occupancy_reading: state whether the document lists the FULL floor stack of this building
  (including already-leased floors) or ONLY the vacant space on offer. Answer "full_stack",
  "available_only" or "unknown".
- Match each building by the exact building_name given below so we can join the answers back.
"""

_SPACE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "floor_label": {"type": "STRING", "nullable": True},
        "area_sqft": {"type": "INTEGER", "nullable": True},
        "condition": {"type": "STRING", "nullable": True},
        "condition_detail": {"type": "STRING", "nullable": True},
        "timeline": {"type": "STRING", "nullable": True},
        "occupancy": {"type": "STRING", "enum": ["available", "occupied", "unknown"]},
        "rent_psf": {"type": "NUMBER", "nullable": True},
        "cam_psf": {"type": "NUMBER", "nullable": True},
        "notes": {"type": "STRING", "nullable": True},
    },
    "required": ["floor_label", "area_sqft", "occupancy"],
}

_CONTACT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "name": {"type": "STRING", "nullable": True},
        "designation": {"type": "STRING", "nullable": True},
        "phone": {"type": "STRING", "nullable": True},
        "email": {"type": "STRING", "nullable": True},
    },
}

EXTRACTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "report_period": {"type": "STRING", "nullable": True},
        "document_note": {"type": "STRING", "nullable": True},
        "buildings": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "building_name": {"type": "STRING"},
                    "address_locality": {"type": "STRING", "nullable": True},
                    "city": {"type": "STRING", "nullable": True},
                    "asset_type": {
                        "type": "STRING",
                        "enum": ["office", "retail", "industrial", "warehouse",
                                 "land", "residential", "mixed"],
                    },
                    "transaction_type": {
                        "type": "STRING",
                        "enum": ["lease", "sale", "managed_office", "mixed"],
                    },
                    "building_structure": {"type": "STRING", "nullable": True},
                    "total_building_size_sqft": {"type": "INTEGER", "nullable": True},
                    "total_size_estimated": {"type": "BOOLEAN", "nullable": True},
                    "total_building_size_basis": {"type": "STRING", "nullable": True},
                    "typical_floor_plate_sqft": {"type": "INTEGER", "nullable": True},
                    "total_available_sqft": {"type": "INTEGER", "nullable": True},
                    "disclosure_mode": {
                        "type": "STRING",
                        "enum": ["full_stack", "available_only", "unknown"],
                    },
                    "spaces": {"type": "ARRAY", "items": _SPACE_SCHEMA},
                    "contacts": {"type": "ARRAY", "items": _CONTACT_SCHEMA},
                    "evidence": {"type": "STRING", "nullable": True},
                },
                "required": ["building_name", "asset_type", "transaction_type",
                             "disclosure_mode", "spaces"],
            },
        },
    },
    "required": ["buildings"],
}

GAPFILL_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "buildings": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "building_name": {"type": "STRING"},
                    "total_building_size_sqft": {"type": "INTEGER", "nullable": True},
                    "total_building_size_basis": {"type": "STRING", "nullable": True},
                    "derived": {"type": "BOOLEAN", "nullable": True},
                    "building_structure": {"type": "STRING", "nullable": True},
                    "address_locality": {"type": "STRING", "nullable": True},
                    "typical_floor_plate_sqft": {"type": "INTEGER", "nullable": True},
                    "total_available_sqft": {"type": "INTEGER", "nullable": True},
                    "occupancy_reading": {
                        "type": "STRING",
                        "enum": ["full_stack", "available_only", "unknown"],
                    },
                    "reasoning": {"type": "STRING", "nullable": True},
                },
                "required": ["building_name"],
            },
        },
    },
    "required": ["buildings"],
}
