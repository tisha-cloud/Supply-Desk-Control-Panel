"""
The three categories the desk trades, and the rule that separates a managed
requirement from a co-working one.

The desk lists three things: conventional space, managed / co-working space,
and space for sale. Managed and co-working are deliberately *one* listing
category, because the listing is identical - the same operator, the same
centre, the same seats. What differs is only the size of the requirement that
walks in the door:

    fewer than 15 seats  ->  co-working
    15 seats or more     ->  managed

So the product name is a property of the *requirement*, never of the record.
Storing it on the building was what produced two categories that no one could
tell apart when editing: the same Table Space centre could be filed either way
depending on who typed it in, and a co-working filter then hid managed stock
that was equally available.

`canonical_supply_type` folds the old `coworking` value back into `managed` so
records written before this rule still read correctly; `product_for_seats`
applies the rule at the point it actually matters, when a requirement is
turned into a proposal.
"""
from typing import Any, Dict, List, Optional

# Below this a requirement is co-working; at or above it, managed. The user's
# rule is "less than 15 is co-working, more than 15 is managed"; 15 exactly is
# read as managed, so the two halves cover every number with no gap.
MANAGED_SEAT_THRESHOLD = 15

# What a record may be filed as.
LISTING_TYPES = ("conventional", "managed", "sale")

LISTING_LABELS = {
    "conventional": "Conventional",
    "managed": "Managed / Co-working",
    "sale": "Sale",
}

# Values that existed before managed and co-working were merged, plus the
# vocabulary the supply files and prompts use for the same thing.
ALIASES = {
    "coworking": "managed",
    "co-working": "managed",
    "co working": "managed",
    "flex": "managed",
    "managed office": "managed",
    "conventional office": "conventional",
    "lease": "conventional",
    "other": "other",
}


def canonical_supply_type(value: Any, default: Optional[str] = None) -> Optional[str]:
    """
    The listing category a stored or user-supplied value belongs to.

    Returns None (or `default`) for anything unrecognised rather than guessing,
    so a typo in an import parameter fails loudly instead of silently filing
    stock in the wrong category.
    """
    text = str(value or "").strip().lower()
    if not text:
        return default
    text = ALIASES.get(text, text)
    if text in LISTING_TYPES or text == "other":
        return text
    return default


def stored_supply_types(listing: Optional[str]) -> List[str]:
    """
    Every value in the database that belongs to a listing category.

    Managed covers rows written as `coworking` before the merge, which is why
    a query filters on this list rather than on equality.
    """
    if listing == "managed":
        return ["managed", "coworking"]
    return [listing] if listing else []


def product_for_seats(seats: Any) -> Optional[str]:
    """
    Which product a requirement for `seats` desks is asking for.

    None when no headcount was given - an area-based brief has no seat count
    and is not a flex requirement at all.
    """
    try:
        count = float(seats)
    except (TypeError, ValueError):
        return None
    if count <= 0:
        return None
    return "coworking" if count < MANAGED_SEAT_THRESHOLD else "managed"


def product_label(product: Optional[str]) -> str:
    return {"coworking": "Co-working", "managed": "Managed Office",
            "conventional": "Conventional", "sale": "Sale"}.get(product or "", "")


def describe_product(product: Optional[str], seats: Any) -> str:
    """A sentence the UI can show explaining why a requirement was labelled."""
    if not product or product not in ("coworking", "managed"):
        return ""
    try:
        count = int(float(seats))
    except (TypeError, ValueError):
        return ""
    if product == "coworking":
        return ("%d seats is under %d, so this is quoted as co-working; the same "
                "centres supply it." % (count, MANAGED_SEAT_THRESHOLD))
    return ("%d seats is %d or more, so this is quoted as a managed office."
            % (count, MANAGED_SEAT_THRESHOLD))
