"""
Where a building is, and what is around it.

Two Google services, both optional and both billed per call:

  Static Maps   draws the map image on a location slide.
  Places        finds the metro, hospitals, hotels and restaurants nearby.

Everything is cached on disk, keyed by what was actually asked for. That is not
a performance nicety: Places is charged at roughly 30 USD per thousand calls,
and a deck asks about every option in it, so rebuilding the same proposal twice
would otherwise be billed twice. Cached, a second build of the same shortlist
costs nothing at all.

Without a key nothing here fails - it returns nothing, and the deck is built
without map slides. A proposal is still a proposal without a map; a crash in
the middle of generating one is not.
"""
import hashlib
import json
import math
import os
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import config

STATIC_MAP_URL = "https://maps.googleapis.com/maps/api/staticmap"
NEARBY_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"

# What to look for around a building, and what to call it on the slide. Each
# entry is one paid Places call per building, so the list is deliberately
# short: these are the four a tenant actually asks about.
AMENITY_TYPES: List[Tuple[str, str]] = [
    ("subway_station", "Metro"),
    ("hospital", "Hospital"),
    ("lodging", "Hotel"),
    ("restaurant", "Dining"),
]

# How far out to look. Wider than this and "nearby" stops meaning walkable.
NEARBY_RADIUS_M = 1500

# Places results go stale slowly - a metro station does not move - so the cache
# is kept for a month rather than minutes.
PLACES_TTL = 30 * 24 * 3600


def _cache_path(kind: str, key: str, suffix: str) -> str:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:24]
    return os.path.join(config.MAP_CACHE_DIR, "%s_%s%s" % (kind, digest, suffix))


def _get(url: str, timeout: int = 20) -> Optional[bytes]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read() if response.status == 200 else None
    except Exception:
        return None


def coordinates(value: Any) -> Optional[Tuple[float, float]]:
    """
    Read a "lat, lng" pair, or None.

    Records carry the pair as a single string because that is how the sheet
    holds it. Anything that is not two numbers in Bengaluru's part of the world
    is rejected rather than plotted somewhere wrong.
    """
    if isinstance(value, (list, tuple)) and len(value) == 2:
        parts = list(value)
    else:
        parts = str(value or "").split(",")
    if len(parts) != 2:
        return None
    try:
        lat, lng = float(str(parts[0]).strip()), float(str(parts[1]).strip())
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    if lat == 0 and lng == 0:
        return None
    return lat, lng


def distance_m(a: Tuple[float, float], b: Tuple[float, float]) -> int:
    """Great-circle metres between two points."""
    radius = 6371000.0
    lat1, lng1 = math.radians(a[0]), math.radians(a[1])
    lat2, lng2 = math.radians(b[0]), math.radians(b[1])
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2)
    return int(round(2 * radius * math.asin(math.sqrt(h))))


def marker_label(position: int) -> str:
    """
    The character on a map pin for option `position`.

    Static Maps allows exactly one alphanumeric character per marker, so
    options past nine continue into letters. The slide prints a key beside the
    map, because a pin reading "C" means nothing on its own.
    """
    if position <= 9:
        return str(position)
    offset = position - 10
    return chr(ord("A") + offset) if offset < 26 else "*"


# ------------------------------------------------------------------ the map
def static_map(points: List[Dict[str, Any]], size: Tuple[int, int] = (640, 420),
               zoom: Optional[int] = None) -> Optional[bytes]:
    """
    A map image with a numbered pin per point, or None.

    `points` are dicts with `lat`, `lng` and an optional `label`. With one
    point the map centres on it; with several, Google frames them all, which is
    what makes a shortlist readable as a cluster rather than a list.
    """
    if not config.maps_configured() or not points:
        return None

    params = [("size", "%dx%d" % size), ("scale", "2"), ("maptype", "roadmap")]
    if len(points) == 1:
        params.append(("center", "%s,%s" % (points[0]["lat"], points[0]["lng"])))
        params.append(("zoom", str(zoom or 15)))
    elif zoom:
        params.append(("zoom", str(zoom)))

    for point in points:
        label = str(point.get("label") or "").strip()
        marker = "color:0xd32f2f|"
        if label:
            marker += "label:%s|" % label[0].upper()
        marker += "%s,%s" % (point["lat"], point["lng"])
        params.append(("markers", marker))

    query = urllib.parse.urlencode(params)
    cached = _cache_path("map", query, ".png")
    if os.path.isfile(cached):
        with open(cached, "rb") as fh:
            return fh.read()

    data = _get("%s?%s&key=%s" % (STATIC_MAP_URL, query,
                                 urllib.parse.quote(config.GOOGLE_MAPS_API_KEY)))
    # A Static Maps error still answers 200, with a tiny PNG carrying the
    # message. Anything that small is not a map.
    if not data or len(data) < 2000:
        return None
    with open(cached, "wb") as fh:
        fh.write(data)
    return data


# ------------------------------------------------------------- what is near
def nearby(lat: float, lng: float, limit_per_type: int = 3) -> List[Dict[str, Any]]:
    """
    Notable places around a point, grouped by kind and sorted by distance.

    Cached for a month per location: this is the expensive call, and a metro
    station does not move.
    """
    if not config.maps_configured():
        return []

    key = "%.5f,%.5f,%d" % (lat, lng, NEARBY_RADIUS_M)
    cached = _cache_path("near", key, ".json")
    if os.path.isfile(cached):
        try:
            with open(cached, encoding="utf-8") as fh:
                stored = json.load(fh)
            if time.time() - stored.get("at", 0) < PLACES_TTL:
                return stored["places"]
        except Exception:
            pass

    origin = (lat, lng)
    found: List[Dict[str, Any]] = []
    for place_type, label in AMENITY_TYPES:
        query = urllib.parse.urlencode({
            "location": "%s,%s" % (lat, lng),
            "radius": NEARBY_RADIUS_M,
            "type": place_type,
            "key": config.GOOGLE_MAPS_API_KEY,
        })
        raw = _get("%s?%s" % (NEARBY_URL, query))
        if not raw:
            continue
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        if body.get("status") not in ("OK", "ZERO_RESULTS"):
            continue

        entries = []
        for result in body.get("results", []):
            location = (result.get("geometry") or {}).get("location") or {}
            if "lat" not in location or "lng" not in location:
                continue
            entries.append({
                "kind": label,
                "name": result.get("name") or "",
                "metres": distance_m(origin, (location["lat"], location["lng"])),
                "rating": result.get("rating"),
            })
        entries.sort(key=lambda e: e["metres"])
        found += entries[:limit_per_type]

    try:
        with open(cached, "w", encoding="utf-8") as fh:
            json.dump({"at": time.time(), "places": found}, fh)
    except OSError:
        pass
    return found


def describe_nearby(places: List[Dict[str, Any]]) -> List[str]:
    """One readable line per kind, nearest first: 'Metro: Indiranagar (850 m)'."""
    by_kind: Dict[str, List[Dict[str, Any]]] = {}
    for place in places:
        by_kind.setdefault(place["kind"], []).append(place)

    lines = []
    for _, label in AMENITY_TYPES:
        entries = by_kind.get(label) or []
        if not entries:
            continue
        rendered = ", ".join(
            "%s (%s)" % (e["name"], "%d m" % e["metres"] if e["metres"] < 1000
                         else "%.1f km" % (e["metres"] / 1000.0))
            for e in entries[:3])
        lines.append("%s: %s" % (label, rendered))
    return lines


def option_points(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    The plottable options out of a shortlist, numbered as the deck numbers them.

    An option with no coordinates is skipped rather than guessed at, and keeps
    its option number so the map key still matches the slides.
    """
    points = []
    for position, record in enumerate(records, start=1):
        pair = coordinates(record.get("location_map"))
        if not pair:
            continue
        points.append({
            "lat": pair[0], "lng": pair[1],
            "label": marker_label(position),
            "option": position,
            "name": record.get("building_name") or "",
        })
    return points
