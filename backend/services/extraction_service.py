"""
Runs the landlord-document extraction pipeline and publishes its output to
Supabase.

The pipeline itself is not reimplemented here - `../../extraction` already does
the hard parts (native PDF reading, the colour-coded vacancy detection, the
occupancy derivation). This module drives it, streams progress into
`ingest_jobs`, and maps its row dictionaries onto the database schema.
"""
import os
import shutil
import traceback
from typing import Any, Dict, List, Optional

import config
import db
from services import categories

# these resolve because config.py put ../../extraction on sys.path
import master_extract as mx                       # noqa: E402
from extractor import docs, rows as rowbuilder, schema  # noqa: E402
from extractor.llm import GeminiClient            # noqa: E402
from extractor.llm.gemini import CacheMiss, QuotaExhausted  # noqa: E402


def _micro_market_cache() -> Dict[str, Optional[str]]:
    return {}


def run_extraction(job_id: str, source_dir: Optional[str] = None,
                   developer_filter: Optional[str] = None,
                   limit: int = 0, workers: int = 2,
                   cache_only: bool = False, gapfill: bool = False) -> Dict[str, Any]:
    """
    Read every document under `source_dir` and publish the results.

    Returns a stats dict; also mirrors progress into the ingest_jobs row so the
    UI can follow along without polling the process.
    """
    source_dir = source_dir or config.SUPPLY_DIR
    stats: Dict[str, Any] = {
        "files": 0, "extracted": 0, "no_data": 0, "failed": 0,
        "buildings": 0, "spaces": 0, "contacts": 0, "derived_rows": 0,
        "llm_calls": 0, "cache_hits": 0, "errors": [],
    }

    db.update_job(job_id, status="running", started_at="now()")
    db.append_job_log(job_id, "Scanning %s ..." % source_dir)

    items = mx.scan(source_dir)
    items, superseded = mx.dedupe(items)
    if developer_filter:
        needle = developer_filter.lower()
        items = [i for i in items if needle in i["rel_path"].lower()]
    if limit:
        items = items[:limit]

    stats["files"] = len(items)
    db.update_job(job_id, total_files=len(items))
    db.append_job_log(job_id, "%d files to read (%d duplicates/older editions set aside)."
                      % (len(items), len(superseded)))

    client = GeminiClient(cache_dir=mx.CACHE_DIR, cache_only=cache_only, verbose=False)
    micro_markets = _micro_market_cache()

    for index, item in enumerate(items, start=1):
        try:
            item, buildings = mx.process_item(client, item, gapfill, False, None)
        except QuotaExhausted as exc:
            stats["errors"].append(str(exc))
            db.append_job_log(job_id, "Stopped: %s" % exc)
            break
        except Exception as exc:
            item["status"] = "FAILED"
            item["detail"] = str(exc)[:300]
            buildings = []

        status = item.get("status") or "FAILED"
        if status == "EXTRACTED":
            stats["extracted"] += 1
        elif status == "NO DATA":
            stats["no_data"] += 1
        else:
            stats["failed"] += 1

        _record_source_document(job_id, item)

        published = _publish_buildings(item, buildings, micro_markets)
        stats["buildings"] += published["buildings"]
        stats["spaces"] += published["spaces"]
        stats["contacts"] += published["contacts"]
        stats["derived_rows"] += published["derived"]

        db.update_job(job_id, done_files=index,
                      buildings_upserted=stats["buildings"],
                      spaces_upserted=stats["spaces"])
        db.append_job_log(job_id, "(%d/%d) %-11s %2d bldg  %s"
                          % (index, len(items), status,
                             len(buildings or []), item["rel_path"][:70]))

    stats["llm_calls"] = client.calls
    stats["cache_hits"] = client.cache_hits
    return stats


def _record_source_document(job_id: str, item: Dict[str, Any]) -> None:
    try:
        db.client().table("source_documents").insert({
            "job_id": job_id,
            "filename": item.get("filename"),
            "rel_path": item.get("rel_path"),
            "sha1": item.get("sha1"),
            "kind": item.get("kind"),
            "developer": item.get("developer"),
            "report_period": item.get("period"),
            "status": item.get("status"),
            "detail": (item.get("detail") or "")[:2000],
            "bytes": item.get("size"),
        }).execute()
    except Exception:
        pass


def _publish_buildings(item: Dict[str, Any], buildings: List[Dict[str, Any]],
                       micro_markets: Dict[str, Optional[str]]) -> Dict[str, int]:
    """Turn one document's extracted buildings into database rows."""
    written = {"buildings": 0, "spaces": 0, "contacts": 0, "derived": 0}
    if not buildings:
        return written

    source_meta = {
        "rel_path": item["rel_path"], "kind": item["kind"],
        "period": item.get("period", ""), "folder": item.get("folder", ""),
    }
    developer_name = item.get("developer") or ""
    developer_id = db.ensure_organisation(developer_name, "developer")

    # Read once per document rather than once per building in it.
    declared = {item.get("folder", ""): declared_category(item.get("folder", ""))}

    for building in buildings:
        try:
            built, diagnostics = rowbuilder.build_building_rows(
                building, developer_name, source_meta)
        except Exception:
            continue
        if not built:
            continue

        head = built[0]
        code = head.get("BLR - Categorization") or ""
        if code and code not in micro_markets:
            micro_markets[code] = db.ensure_micro_market(code)

        supply = "conventional"
        if head.get("_transaction_type") == "sale":
            supply = "sale"
        elif head.get("_transaction_type") == "managed_office":
            supply = "managed"
        elif head.get("_asset_type") not in ("office", "mixed"):
            supply = "other"
        # What the operator declared at upload beats what the document implies.
        # The guess above reads a transaction type out of prose; somebody who
        # opened the file and chose a category knows.
        supply = declared.get(item.get("folder", "")) or supply

        try:
            building_id = db.upsert_building({
                "name": head.get("Building Name"),
                "address": head.get("Building Address / Location"),
                "locality": head.get("_locality"),
                "city": head.get("_city") or "Bengaluru",
                "micro_market_id": micro_markets.get(code),
                "developer_id": developer_id,
                "supply_type": supply,
                "asset_type": head.get("_asset_type") or "office",
                "structure": head.get("Building Structure"),
                "total_size_sqft": head.get("_total_sqft"),
                "total_size_is_estimated": bool(
                    building.get("total_size_estimated")),
                "total_size_basis": head.get("_total_basis"),
                "disclosure_mode": head.get("_disclosure"),
                "source_file": item["rel_path"],
                "report_period": item.get("period"),
            })
        except Exception:
            continue
        written["buildings"] += 1

        spaces = []
        for row in built:
            if not (row.get("Available  Floors") or row.get("_area_sqft")):
                continue
            spaces.append({
                "floor_label": row.get("Available  Floors") or None,
                "area_sqft": row.get("_area_sqft"),
                "condition": row.get("Condition") or None,
                "condition_detail": row.get("_condition_detail") or None,
                "timeline": row.get("Timeline") or None,
                "occupancy": row.get("_occupancy") or "unknown",
                "rent_psf": row.get("_rent_psf"),
                "cam_psf": row.get("_cam_psf"),
                "is_derived": bool(row.get("_derived")),
                "derivation_note": row.get("_derived") or None,
                "evidence": row.get("_evidence") or None,
                "notes": row.get("_notes") or None,
            })
            if row.get("_derived"):
                written["derived"] += 1

        try:
            written["spaces"] += db.replace_spaces(
                building_id, spaces, source_file=item["rel_path"])
        except Exception:
            pass

        contacts = building.get("contacts") or []
        if contacts:
            try:
                written["contacts"] += db.upsert_contacts(
                    contacts, building_id=building_id)
            except Exception:
                pass

    return written


# Written beside the uploaded files to record what the operator said the
# supply is. A dotfile so the pipeline, which selects documents by extension,
# never mistakes it for something to read.
CATEGORY_MARKER = ".supply-category"


def stage_uploads(files: List[str], developer: str,
                  supply_type: Optional[str] = None) -> str:
    """
    Put uploaded files where the pipeline expects them.

    The pipeline derives the landlord from the folder name, so an upload has to
    land in a folder named after that landlord. `supply_type` records what the
    operator says this stock is; the pipeline can guess from the document, but
    a person who has read the file knows better, and the guess is only a guess.
    """
    target = os.path.join(config.SUPPLY_DIR, developer.strip() or "Uploads")
    os.makedirs(target, exist_ok=True)
    for path in files:
        shutil.copy2(path, os.path.join(target, os.path.basename(path)))

    category = categories.canonical_supply_type(supply_type)
    if category:
        with open(os.path.join(target, CATEGORY_MARKER), "w", encoding="utf-8") as fh:
            fh.write(category)
    return target


def declared_category(folder: str) -> Optional[str]:
    """What the operator said this folder holds, if they said anything."""
    if not folder:
        return None
    marker = os.path.join(config.SUPPLY_DIR, folder, CATEGORY_MARKER)
    try:
        with open(marker, encoding="utf-8") as fh:
            return categories.canonical_supply_type(fh.read().strip())
    except OSError:
        return None
