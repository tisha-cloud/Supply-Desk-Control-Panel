"""
Builds 'Blr - Conventional - Options Sheet' from the raw landlord files in
BLR_Builders_Developers_Supply/, using Gemini to read each document.

    python master_extract.py                     # full run
    python master_extract.py --developer Bagmane # one landlord
    python master_extract.py --limit 5           # smoke test
    python master_extract.py --refresh           # ignore the response cache

Responses are cached on disk by file hash + prompt version, so re-runs after a
code change cost nothing. The reference workbook is opened read-only.
"""
import argparse
import csv
import os
import re
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher

from extractor import docs, rows as rowbuilder, schema, verify, workbook
from extractor.llm import GeminiClient, LLMError
from extractor.llm.gemini import CacheMiss, QuotaExhausted
from extractor.llm.gemini import sha1_file, sha1_text
from extractor.llm import prompts

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUPPLY_DIR = os.path.join(BASE_DIR, "BLR_Builders_Developers_Supply")
CACHE_DIR = os.path.join(BASE_DIR, ".llm_cache")
DEFAULT_REFERENCE = r"C:\Users\devil\Downloads\Blr - Conventional - Options Sheet -2026.xlsx"
DEFAULT_OUTPUT = os.path.join(BASE_DIR, "Blr - Conventional - Options Sheet - AUTO.xlsx")

SKIP_EXTS = {".db", ".ini", ".lnk", ".tmp", ".zip"}
MONTH_ORDER = {m: i for i, m in enumerate(docs.MONTHS, start=1)}


# ------------------------------------------------------------------ inventory
def period_sort_key(period):
    if not period:
        return (0, 0)
    parts = period.split()
    if len(parts) == 2:
        return (int(parts[1]), MONTH_ORDER.get(parts[0].lower(), 0))
    try:
        return (int(parts[0]), 0)
    except ValueError:
        return (0, 0)


def _dedup_stem(filename):
    stem = os.path.splitext(filename)[0].lower()
    stem = re.sub(r"\(\d+\)", " ", stem)
    stem = re.sub(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", " ", stem)
    stem = re.sub(r"\b(19|20)\d{2}\b|\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b|\b\d{6,8}\b", " ", stem)
    stem = re.sub(r"[^a-z ]+", " ", stem)
    stem = re.sub(r"\b[a-z]\b", " ", stem)  # stray initials like the trailing 'K'
    return re.sub(r"\s+", " ", stem).strip()


def scan(supply_dir):
    items = []
    for root, _dirs, files in os.walk(supply_dir):
        for name in sorted(files):
            ext = os.path.splitext(name)[1].lower()
            if ext in SKIP_EXTS or name.startswith("~$"):
                continue
            abs_path = os.path.join(root, name)
            rel_path = os.path.relpath(abs_path, supply_dir)
            parts = rel_path.split(os.sep)[:-1] or ["Root"]
            items.append({
                "abs_path": abs_path,
                "rel_path": rel_path,
                "filename": name,
                "folder_parts": parts,
                "folder": parts[0],
                "developer": schema.canonical_developer(parts),
                "kind": docs.classify(abs_path),
                "size": os.path.getsize(abs_path),
                "period": docs.guess_period(rel_path) or docs.guess_period(parts[0]),
                "sha1": sha1_file(abs_path),
                "status": "",
                "detail": "",
            })
    return items


def dedupe(items):
    """Drop byte-identical copies, then supersede older monthly editions."""
    kept, superseded = [], []
    by_hash = {}
    for item in items:
        first = by_hash.get(item["sha1"])
        if first is None:
            by_hash[item["sha1"]] = item
            kept.append(item)
        else:
            item["status"] = "DUPLICATE"
            item["detail"] = "byte-identical to " + first["rel_path"]
            superseded.append(item)

    survivors = []
    groups = {}
    for item in kept:
        groups.setdefault((item["developer"].lower(), _dedup_stem(item["filename"])), []).append(item)

    for group in groups.values():
        if len(group) == 1:
            survivors.extend(group)
            continue
        dated = [g for g in group if g["period"]]
        if len(dated) < 2:
            survivors.extend(group)
            continue
        newest = max(dated, key=lambda g: period_sort_key(g["period"]))
        for item in group:
            if item is newest:
                survivors.append(item)
            elif item in dated and period_sort_key(item["period"]) < period_sort_key(newest["period"]):
                item["status"] = "SUPERSEDED"
                item["detail"] = "older edition; %s supersedes it" % newest["filename"]
                superseded.append(item)
            else:
                survivors.append(item)

    # Same document filed under two landlord folders with different bytes -> keep both.
    survivors.sort(key=lambda i: i["rel_path"])
    return survivors, superseded


# ------------------------------------------------------------------- LLM work
def extract_document(client, item, refresh=False):
    parts, kind = docs.build_parts(item["abs_path"], client)
    instructions = prompts.EXTRACTION_INSTRUCTIONS.format(
        developer=item["developer"], filename=item["filename"])
    payload = [client.text_part(instructions)] + parts

    cache_key = "p1_%s_%s_%s" % (prompts.PROMPT_VERSION_P1, item["sha1"][:16],
                                 schema.clean_name(item["developer"]).lower().replace(" ", "")[:20])
    if refresh:
        path = os.path.join(CACHE_DIR, cache_key + ".json")
        if os.path.exists(path):
            os.remove(path)

    result = client.generate_json(
        payload,
        system=prompts.SYSTEM_PROMPT,
        schema=prompts.EXTRACTION_SCHEMA,
        cache_key=cache_key,
        label=item["rel_path"],
    )
    return result, kind


GAP_FIELDS = ["total_building_size_sqft", "building_structure", "address_locality"]


def find_gaps(buildings):
    gaps = []
    for building in buildings:
        missing = []
        if not building.get("total_building_size_sqft"):
            missing.append("total_building_size_sqft")
        if not building.get("building_structure"):
            missing.append("building_structure")
        if not building.get("address_locality"):
            missing.append("address_locality")
        if (building.get("disclosure_mode") or "unknown") == "unknown":
            missing.append("occupancy_reading")
        if missing and (building.get("spaces") or building.get("total_available_sqft")):
            gaps.append((building, missing))
    return gaps


def gapfill_document(client, item, buildings, refresh=False):
    """Second LLM pass: hunt specifically for the fields pass 1 left blank."""
    gaps = find_gaps(buildings)
    if not gaps:
        return 0

    gap_list = "\n".join(
        "- %s  ->  missing: %s" % (b.get("building_name", "?"), ", ".join(m)) for b, m in gaps)
    parts, _kind = docs.build_parts(item["abs_path"], client)
    instructions = prompts.GAPFILL_INSTRUCTIONS.format(
        developer=item["developer"], filename=item["filename"], gap_list=gap_list)

    # sha1, not hash(): Python's string hash is salted per process, which would
    # give this entry a new key on every run and re-bill every gap-fill call.
    cache_key = "p2_%s_%s_%s" % (prompts.PROMPT_VERSION_P2, item["sha1"][:16],
                                 sha1_text(gap_list)[:12])
    if refresh:
        path = os.path.join(CACHE_DIR, cache_key + ".json")
        if os.path.exists(path):
            os.remove(path)

    try:
        result = client.generate_json(
            [client.text_part(instructions)] + parts,
            system=prompts.SYSTEM_PROMPT,
            schema=prompts.GAPFILL_SCHEMA,
            cache_key=cache_key,
            label="gapfill " + item["rel_path"],
        )
    except QuotaExhausted:
        raise
    except LLMError as exc:
        print("      [gapfill failed] %s: %s" % (item["rel_path"], exc), flush=True)
        return 0

    by_name = {schema.clean_name(b.get("building_name")).lower(): b for b in buildings}
    filled = 0
    for answer in result.get("buildings", []):
        name = schema.clean_name(answer.get("building_name")).lower()
        target = by_name.get(name)
        if target is None:
            best, score = None, 0.0
            for key, building in by_name.items():
                ratio = SequenceMatcher(None, name, key).ratio()
                if ratio > score:
                    best, score = building, ratio
            target = best if score >= 0.85 else None
        if target is None:
            continue

        for field in ("total_building_size_sqft", "building_structure", "address_locality",
                      "typical_floor_plate_sqft", "total_available_sqft"):
            value = answer.get(field)
            if value and not target.get(field):
                target[field] = value
                filled += 1
                if field == "total_building_size_sqft":
                    basis = answer.get("total_building_size_basis") or answer.get("reasoning") or ""
                    estimated = bool(answer.get("derived"))
                    target["total_size_estimated"] = estimated
                    target["total_building_size_basis"] = (
                        ("ESTIMATED - " if estimated else "") + str(basis))[:300]

        reading = answer.get("occupancy_reading")
        if reading and reading != "unknown" and (target.get("disclosure_mode") or "unknown") == "unknown":
            target["disclosure_mode"] = reading
            filled += 1
    return filled


def process_item(client, item, do_gapfill, refresh, stop_flag=None):
    if stop_flag is not None and stop_flag.is_set():
        item["status"] = "SKIPPED - QUOTA"
        item["detail"] = "daily LLM quota exhausted before this file was reached"
        item["_buildings"] = []
        return item, []
    try:
        result, kind = extract_document(client, item, refresh=refresh)
    except CacheMiss:
        item["status"] = "NOT EXTRACTED"
        item["detail"] = "no cached result; re-run without --cache-only once quota allows"
        item["_buildings"] = []
        return item, []
    except QuotaExhausted as exc:
        if stop_flag is not None:
            stop_flag.set()
        item["status"] = "SKIPPED - QUOTA"
        item["detail"] = str(exc)[:400]
        item["_buildings"] = []
        return item, []
    except Exception as exc:
        item["status"] = "FAILED"
        item["detail"] = str(exc)[:400]
        item["_buildings"] = []
        return item, []

    buildings = result.get("buildings") or []
    if do_gapfill and buildings:
        try:
            filled = gapfill_document(client, item, buildings, refresh=refresh)
            if filled:
                item["detail"] = "gap-fill supplied %d field(s)" % filled
        except CacheMiss:
            pass
        except QuotaExhausted:
            if stop_flag is not None:
                stop_flag.set()
            item["detail"] = "gap-fill skipped: daily LLM quota exhausted"
        except Exception as exc:
            item["detail"] = "gap-fill error: %s" % str(exc)[:200]

    if not item["period"]:
        item["period"] = schema.clean_name(result.get("report_period"))
    if not buildings:
        item["status"] = "NO DATA"
        item["detail"] = schema.clean_name(result.get("document_note"))[:300] or "no property data found"
    else:
        item["status"] = "EXTRACTED"
    item["_buildings"] = buildings
    item["_kind"] = kind
    return item, buildings


# -------------------------------------------------------------- sheet assembly
def is_master_row(row):
    if row.get("_city") and not schema.is_bangalore(row["_city"], row.get("_locality"), row.get("_building")):
        return False
    if row.get("BLR - Categorization") == "Outside BLR":
        return False
    if row.get("_asset_type") not in ("office", "mixed"):
        return False
    if row.get("_transaction_type") in ("sale", "managed_office"):
        return False
    return True


def other_asset_row(row):
    asset = row.get("_asset_type", "office")
    if row.get("_transaction_type") == "managed_office":
        asset = "managed office"
    return {
        "Asset Type": asset.title(),
        "City": row.get("_city", ""),
        "Micro-Market": row.get("BLR - Categorization", ""),
        "Builder / Developer": row.get("Builder / Developer", ""),
        "Building Name": row.get("Building Name", ""),
        "Address / Location": row.get("Building Address / Location", ""),
        "Building Structure": row.get("Building Structure", ""),
        "Total Building Size [In Sq. Ft.]": row.get("Total Building Size [In Sq. Ft.]", ""),
        "Available  Floors": row.get("Available  Floors", ""),
        "Available - Area in Sft": row.get("Available - Area in Sft", ""),
        "Condition": row.get("Condition", ""),
        "Timeline": row.get("Timeline", ""),
        "Source File": row.get("_source_file", ""),
    }


def audit_row(row):
    return {
        "Developer": row.get("Builder / Developer", ""),
        "Building Name": row.get("Building Name", ""),
        "Micro-Market": row.get("BLR - Categorization", ""),
        "City": row.get("_city", ""),
        "Asset Type": row.get("_asset_type", ""),
        "Transaction": row.get("_transaction_type", ""),
        "Floor": row.get("Available  Floors", ""),
        "Area in Sft": row.get("Available - Area in Sft", ""),
        "Condition": row.get("Condition", ""),
        "Condition Detail": row.get("_condition_detail", ""),
        "Timeline": row.get("Timeline", ""),
        "Occupancy": row.get("_occupancy", ""),
        "Rent /sft/mo": row.get("_rent_psf") or "",
        "CAM /sft/mo": row.get("_cam_psf") or "",
        "Total Building Size": row.get("Total Building Size [In Sq. Ft.]", ""),
        "Size Basis": row.get("_total_basis", ""),
        "Disclosure Mode": row.get("_disclosure", ""),
        "Derivation": row.get("_derived", ""),
        "Evidence": row.get("_evidence", ""),
        "Notes": row.get("_notes", ""),
        "Report Period": row.get("_period", ""),
        "Source File": row.get("_source_file", ""),
    }


def build_poc_rows(contact_index):
    out = []
    serial = 0
    for developer in sorted(contact_index):
        serial += 1
        first = True
        for building, name, phone, email in contact_index[developer]:
            out.append({
                "Sl. No": serial if first else "",
                "Builder / Developer": developer if first else "",
                "Building Name / Location": building,
                "Contact Person": name,
                "Contact Number": phone,
                "Email ID": email,
                "Inventory Status": "Received" if first else "",
            })
            first = False
        out.append({c: "" for c in workbook.POC_COLUMNS})
    return out


def build_sale_rows(sale_buildings):
    out = []
    for idx, entry in enumerate(sorted(sale_buildings, key=lambda e: (e["developer"], e["building"])), 1):
        out.append({
            "Sl. No": idx,
            "Builder - Developer - Portfolio": entry["developer"],
            "Building Name / Location": entry["building"],
            "Address / Location": entry["address"],
            "Contact Person": entry["contact"],
            "Contact Number": entry["phone"],
            "Email ID": entry["email"],
        })
    return out


# --------------------------------------------------------------------- driver
def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--supply-dir", default=SUPPLY_DIR)
    parser.add_argument("--reference", default=DEFAULT_REFERENCE)
    parser.add_argument("--out", default=DEFAULT_OUTPUT)
    parser.add_argument("--developer", default=None, help="substring filter on the landlord folder")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--refresh", action="store_true", help="bypass the on-disk response cache")
    parser.add_argument("--no-gapfill", action="store_true", help="skip the second LLM pass")
    parser.add_argument("--cache-only", action="store_true",
                        help="rebuild from stored responses without spending any LLM quota")
    args = parser.parse_args()

    started = time.time()
    print("=" * 78)
    print("BLR CONVENTIONAL OPTIONS SHEET - AUTOMATED EXTRACTION")
    print("=" * 78, flush=True)

    if not os.path.isdir(args.supply_dir):
        print("[ERROR] supply directory not found: " + args.supply_dir)
        return 1

    print("[1/6] Scanning source files ...", flush=True)
    items = scan(args.supply_dir)
    items, superseded = dedupe(items)
    if args.developer:
        needle = args.developer.lower()
        items = [i for i in items if needle in i["rel_path"].lower()]
    if args.limit:
        items = items[: args.limit]
    print("      %d files to read (%d duplicates/older editions set aside)"
          % (len(items), len(superseded)), flush=True)

    client = GeminiClient(cache_dir=CACHE_DIR, cache_only=args.cache_only)
    print("      model chain: " + ", ".join(client.model_chain), flush=True)

    print("[2/6] %s ..." % ("Replaying cached extractions (no LLM calls)"
                           if args.cache_only else "Reading documents with the LLM"), flush=True)
    processed = []
    stop_flag = threading.Event()
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(process_item, client, item, not args.no_gapfill,
                               args.refresh, stop_flag): item
                   for item in items}
        for done, future in enumerate(as_completed(futures), start=1):
            item = futures[future]
            try:
                item, buildings = future.result()
            except Exception:
                item["status"] = "FAILED"
                item["detail"] = traceback.format_exc(limit=1)[:300]
                buildings = []
                item["_buildings"] = []
            processed.append(item)
            print("      (%d/%d) %-9s %-11s %2d bldg  %s"
                  % (done, len(items), item["kind"], item["status"],
                     len(item.get("_buildings") or []), item["rel_path"][:74]), flush=True)

    print("[3/6] Normalising and deriving occupied space ...", flush=True)
    master_rows, other_rows, audit_rows, derivation_rows = [], [], [], []
    sale_buildings, contact_index = [], {}

    for item in sorted(processed, key=lambda i: i["rel_path"]):
        source_meta = {"rel_path": item["rel_path"], "kind": item["kind"],
                       "period": item["period"], "folder": item["folder"]}
        item["_master_rows"] = 0
        item["_other_rows"] = 0
        for building in item.get("_buildings") or []:
            built, diag = rowbuilder.build_building_rows(building, item["developer"], source_meta)
            derivation_rows.append({
                "Developer": diag["developer"],
                "Building Name": diag["building"],
                "Total Building Size (sft)": schema.indian_format(diag["total_sqft"]) if diag["total_sqft"] else "",
                "Total Size Source": ("Estimated" if diag.get("total_estimated")
                                      else ("Stated" if diag["total_sqft"] else "")),
                "Listed Available (sft)": schema.indian_format(diag["available_sum"]) if diag["available_sum"] else "",
                "Listed Occupied (sft)": schema.indian_format(diag["occupied_listed"]) if diag["occupied_listed"] else "",
                "Derived Balance (sft)": schema.indian_format(diag["balance_sqft"]) if diag["balance_sqft"] else "",
                "Balance Row Emitted": "Yes" if diag["balance_emitted"] else "No",
                "Disclosure Mode": diag["disclosure"],
                "Issue": diag["issue"],
                "Source File": diag["source_file"],
            })

            for row in built:
                audit_rows.append(audit_row(row))
                if is_master_row(row):
                    master_rows.append(row)
                    item["_master_rows"] += 1
                else:
                    other_rows.append(other_asset_row(row))
                    item["_other_rows"] += 1

            head = built[0]
            if head.get("_transaction_type") in ("sale", "mixed") and head.get("_asset_type") != "industrial":
                contacts = building.get("contacts") or [{}]
                primary = contacts[0] if contacts else {}
                if head.get("_transaction_type") == "sale":
                    sale_buildings.append({
                        "developer": item["developer"],
                        "building": head.get("Building Name", ""),
                        "address": head.get("Building Address / Location", ""),
                        "contact": schema.clean_name(primary.get("name")),
                        "phone": schema.clean_name(primary.get("phone")),
                        "email": schema.clean_name(primary.get("email")),
                    })

            for contact in building.get("contacts") or []:
                name = schema.clean_name(contact.get("name"))
                phone = schema.clean_name(contact.get("phone"))
                email = schema.clean_name(contact.get("email"))
                if not (name or phone or email):
                    continue
                entry = (head.get("Building Name", ""), name, phone, email)
                bucket = contact_index.setdefault(item["developer"], [])
                if entry not in bucket:
                    bucket.append(entry)

    master_rows.sort(key=lambda r: (r.get("Builder / Developer", ""), r.get("Building Name", "")))
    print("      %d Master File rows, %d other-asset rows" % (len(master_rows), len(other_rows)),
          flush=True)

    print("[4/6] Verifying against the reference workbook ...", flush=True)
    verification_rows = (verify.compare(master_rows, args.reference)
                         if os.path.exists(args.reference)
                         else [{"Status": "REFERENCE NOT FOUND", "Note": args.reference}])

    print("[5/6] Assembling coverage report ...", flush=True)
    coverage_rows = []
    for item in sorted(processed + superseded, key=lambda i: (i["developer"], i["rel_path"])):
        coverage_rows.append({
            "Developer": item["developer"],
            "Source File": item["rel_path"],
            "Type": item["kind"],
            "Size (MB)": round(item["size"] / 1e6, 2),
            "Report Period": item["period"],
            "Buildings": len(item.get("_buildings") or []),
            "Master Rows": item.get("_master_rows", 0),
            "Other Rows": item.get("_other_rows", 0),
            "Status": item["status"] or "PENDING",
            "Detail": item["detail"],
        })

    print("[6/6] Writing workbook ...", flush=True)
    poc_rows = build_poc_rows(contact_index)
    sale_rows = build_sale_rows(sale_buildings)
    clean_master = [rowbuilder.strip_meta(r) for r in master_rows]

    workbook.build_workbook(
        args.out, clean_master, poc_rows, sale_rows, other_rows,
        audit_rows, derivation_rows, verification_rows, coverage_rows,
        reference_path=args.reference if os.path.exists(args.reference) else None)

    csv_path = os.path.splitext(args.out)[0] + " - Master File.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=schema.MASTER_COLUMNS)
        writer.writeheader()
        writer.writerows(clean_master)

    derived = sum(1 for r in master_rows if r.get("_derived"))
    developers = len({r["Builder / Developer"] for r in master_rows})
    buildings = len({(r["Builder / Developer"], r["Building Name"]) for r in master_rows})
    available = sum(r["_area_sqft"] or 0 for r in master_rows if r["_occupancy"] == "available")
    occupied = sum(r["_area_sqft"] or 0 for r in master_rows if r["_occupancy"] == "occupied")
    failed = [i for i in processed if i["status"] in ("FAILED", "NOT EXTRACTED", "SKIPPED - QUOTA")]
    nodata = [i for i in processed if i["status"] == "NO DATA"]

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print("Files read                 : %d (%d duplicates/older editions skipped)"
          % (len(processed), len(superseded)))
    print("  failed                   : %d" % len(failed))
    print("  no property data         : %d" % len(nodata))
    print("Developers                 : %d" % developers)
    print("Buildings                  : %d" % buildings)
    print("Master File rows           : %d  (of which %d derived balance rows)"
          % (len(master_rows), derived))
    print("Other-asset rows           : %d" % len(other_rows))
    print("Available area             : %s Sft" % schema.indian_format(available))
    print("Occupied area (incl. derived): %s Sft" % schema.indian_format(occupied))
    print("LLM calls                  : %d  (cache hits %d)" % (client.calls, client.cache_hits))
    print("LLM tokens                 : %s in / %s out"
          % (format(client.prompt_tokens, ","), format(client.output_tokens, ",")))
    print("Elapsed                    : %.1f min" % ((time.time() - started) / 60))
    print("Workbook                   : %s" % args.out)
    print("CSV                        : %s" % csv_path)
    if failed:
        print("\nFAILED FILES:")
        for item in failed:
            print("  - %s :: %s" % (item["rel_path"], item["detail"][:160]))
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
