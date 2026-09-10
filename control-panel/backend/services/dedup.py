"""
Finding and merging duplicate organisations.

The supply feeds name landlords loosely. In the live database 163
organisations included 21 near-duplicate pairs: Prestige alone was split
across "Prestige Group" (26 buildings), "Prestige Groups" (2),
"Prestige / UB Group", "Prestige Group & UB Group" and the typo
"Perstige Groups". A filter for Prestige found a quarter of its own stock.

Two mechanisms, deliberately separated:

  org_key() collapses only the differences that cannot mean anything -
  casing, punctuation, and legal suffixes. That runs automatically on write.

  find_duplicates() proposes everything else for a human to confirm. It never
  merges on its own, because "Mantri Developers" and "Maithri Developers" are
  0.90 similar and are different companies.
"""
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

import db

# Suffixes that carry no identity: "Godrej Properties Ltd" is "Godrej Properties".
LEGAL_SUFFIXES = r"(pvt|private|ltd|limited|llp|inc|corp|corporation|co|company|india)"

# Below this two names are not even proposed as a pair.
SUGGEST_THRESHOLD = 0.88


def org_key(name: str) -> str:
    """
    A comparison key for an organisation name.

    Only removes differences that cannot change who the company is. Anything
    requiring judgement - a missing word, a transposed letter - keeps its own
    key and goes to review instead.
    """
    text = re.sub(r"[^a-z0-9\s]+", " ", str(name or "").lower())
    text = re.sub(r"\b%s\b" % LEGAL_SUFFIXES, " ", text)
    text = re.sub(r"\bgroups\b", "group", text)
    text = re.sub(r"\bdevelopers\b", "developer", text)
    text = re.sub(r"\bprojects\b", "project", text)
    return re.sub(r"\s+", " ", text).strip()


def similarity(left: str, right: str) -> float:
    a, b = org_key(left), org_key(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a.startswith(b) or b.startswith(a):
        return max(0.95, SequenceMatcher(None, a, b).ratio())
    return SequenceMatcher(None, a, b).ratio()


def merge_risk(keep_name: str, other_name: str) -> Optional[str]:
    """
    Why a proposed pair deserves a careful look, or None when it is routine.

    The dangerous case is two different companies whose names differ only
    inside the distinguishing word - "Mantri Developers" and "Maithri
    Developers" are 0.94 similar. Those are still shown, because the same
    shape catches a genuine typo ("Perstige Groups"), but never as routine.
    """
    if org_key(keep_name) == org_key(other_name):
        return None
    left = org_key(keep_name).split()
    right = org_key(other_name).split()
    if left and right and left[0] != right[0]:
        return ("the company word itself differs (%s / %s) - these may be "
                "different firms, not spellings of one" % (left[0], right[0]))
    return "one name carries words the other does not - confirm they are the same firm"


def find_duplicates(organisations: List[Dict[str, Any]],
                    usage: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """
    Propose merges, most-used name first within each group.

    Returns one entry per proposed group: the suggested survivor plus the
    others, with how many buildings each is attached to so the reviewer can
    see what a merge would move.
    """
    usage = usage or {}
    remaining = list(organisations)
    groups: List[Dict[str, Any]] = []

    while remaining:
        seed = remaining.pop(0)
        cluster = [seed]
        rest = []
        for other in remaining:
            if similarity(seed["name"], other["name"]) >= SUGGEST_THRESHOLD:
                cluster.append(other)
            else:
                rest.append(other)
        remaining = rest

        if len(cluster) < 2:
            continue

        # The name carrying the most buildings is the one already in use.
        cluster.sort(key=lambda o: (-usage.get(o["id"], 0), len(o["name"])))
        keep, merge = cluster[0], cluster[1:]
        risks = [r for r in (merge_risk(keep["name"], o["name"]) for o in merge) if r]
        groups.append({
            "keep": {**keep, "buildings": usage.get(keep["id"], 0)},
            "merge": [{**o, "buildings": usage.get(o["id"], 0),
                       "risk": merge_risk(keep["name"], o["name"])} for o in merge],
            "confident": not risks,
            "risks": risks,
            "moves": sum(usage.get(o["id"], 0) for o in merge),
        })

    groups.sort(key=lambda g: -g["moves"])
    return groups


def organisation_usage() -> Dict[str, int]:
    """How many buildings reference each organisation, either way round."""
    sb = db.client()
    counts: Dict[str, int] = {}
    rows = sb.table("buildings").select("developer_id, operator_id").limit(5000).execute().data or []
    for row in rows:
        for key in ("developer_id", "operator_id"):
            if row.get(key):
                counts[row[key]] = counts.get(row[key], 0) + 1
    return counts


def duplicate_report() -> List[Dict[str, Any]]:
    sb = db.client()
    organisations = sb.table("organisations").select(
        "id, name, role, offers_managed, offers_coworking").limit(2000).execute().data or []
    return find_duplicates(organisations, organisation_usage())


def merge_organisations(keep_id: str, merge_ids: List[str]) -> Dict[str, int]:
    """
    Repoint everything at `keep_id`, then delete the merged records.

    Every reference has to move before the delete: organisations are
    referenced from three places, and a missed one would either null out a
    landlord (on delete set null) or leave a dangling row.
    """
    merge_ids = [i for i in merge_ids if i and i != keep_id]
    if not merge_ids:
        return {"buildings": 0, "spaces": 0, "contacts": 0, "removed": 0}

    sb = db.client()
    moved = {"buildings": 0, "spaces": 0, "contacts": 0, "removed": 0}

    for column in ("developer_id", "operator_id"):
        rows = sb.table("buildings").select("id").in_(column, merge_ids).execute().data or []
        if rows:
            sb.table("buildings").update({column: keep_id}).in_(column, merge_ids).execute()
            moved["buildings"] += len(rows)

    rows = sb.table("spaces").select("id").in_("operator_id", merge_ids).execute().data or []
    if rows:
        sb.table("spaces").update({"operator_id": keep_id}).in_("operator_id", merge_ids).execute()
        moved["spaces"] += len(rows)

    rows = sb.table("contacts").select("id").in_("organisation_id", merge_ids).execute().data or []
    if rows:
        sb.table("contacts").update({"organisation_id": keep_id}).in_(
            "organisation_id", merge_ids).execute()
        moved["contacts"] += len(rows)

    sb.table("organisations").delete().in_("id", merge_ids).execute()
    moved["removed"] = len(merge_ids)
    return moved
