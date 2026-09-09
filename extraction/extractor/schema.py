"""
Normalisation layer: raw LLM output -> the 11 columns of the Master File sheet.

Column order in the target workbook:
    BLR - Categorization | Options | Builder / Developer | Building Name |
    Building Address / Location | Building Structure | Total Building Size [In Sq. Ft.] |
    Available  Floors | Available - Area in Sft | Condition | Timeline
"""
import re

MASTER_COLUMNS = [
    "BLR - Categorization",
    "Options",
    "Builder / Developer",
    "Building Name",
    "Building Address / Location",
    "Building Structure",
    "Total Building Size [In Sq. Ft.]",
    "Available  Floors",
    "Available - Area in Sft",
    "Condition",
    "Timeline",
]

# Ordered most-specific-first: the first pattern that hits wins.
MICROMARKET_RULES = [
    ("Airport / Devanahalli", r"devanahalli|kiadb\s*aerospace|airport\s*(city|road)|bengaluru\s*international\s*airport|\bkial\b"),
    ("North-BLR", r"hebbal|manyata|nagavara|yelahanka|jakkur|thanisandra|sahakar\s*nagar|sahakarnagar|bellary\s*road|\brt\s*nagar\b|mekhri|hennur|byatarayanapura|kempapura|\bnorth\b\s*(blr|bangalore|bengaluru|zone)"),
    ("E-City", r"e[\s\-]*city|electronic[\s\-]*city|electronics\s*city|bommasandra|konappana|hosur\s*road|neotown"),
    ("Whitefield", r"whitefield|\bepip\b|\bitpl\b|\bitpb\b|hoodi|brooke?field|kundalahalli|varthur|gunjur|nallurhalli|pattandur|siddapura|channasandra|seetharampalya|graphite\s*india"),
    ("Sarjapur Road", r"sarjapur\s*(main\s*)?road|haralur|kasavanahalli|ambalipura|dommasandra|carmelaram"),
    ("HSR Layout", r"\bhsr\b"),
    ("ORR", r"outer\s*ring\s*road|\borr\b|bellandur|marathahalli|kadubeesanahalli|devarabeesanahalli|mahadev[ae]?pura|panathur|yemalur|yamalur|kadubisanahalli|ecoworld|eco\s*world|embassy\s*tech\s*village|doddanekkundi|\bcv\s*raman\s*nagar\b|\bbanaswadi\b"),
    # Domlur/EGL sits on the IRR but trades as Indiranagar stock, so it is matched first.
    ("Indiranagar", r"indira\s*nagar|indiranagar|domlur|embassy\s*golf|\begl\b|old\s*airport\s*road|murugesh\s*palya|murugeshpalya|\bhal\b|kodihalli"),
    ("Koramangala", r"koramangala|intermediate\s*ring\s*road|\birr\b|adugodi|jakkasandra|ejipura"),
    ("Old Madras Road", r"old\s*madras\s*road|\bomr\b|\bkr\s*puram\b|krishnarajapuram|budigere|hoskote|medahalli"),
    ("Bannerghatta Road", r"bannerghatta|\bbg\s*road\b|arekere|hulimavu|\bjayadeva\b"),
    ("South-BLR", r"jp\s*nagar|jayanagar|kanakapura|\bbtm\b|banashankari|\bjp\-nagar\b|bilekahalli|\bbasavanagudi\b"),
    ("West-BLR", r"yeshwanthpur|yeshwantpur|rajajinagar|malleshwaram|peenya|magadi\s*road|mysore\s*road|nagarbhavi|tumkur\s*road|vijayanagar|jalahalli|dasarahalli"),
    ("CBD", r"\bcbd\b|\bcdb\b|chickpet|chickpete|avenue\s*road|\bmg\s*road\b|vittal\s*mallya|lavelle|richmond|st\.?\s*mark|residency\s*road|cunningham|infantry|museum\s*road|kasturba|kastruba|ulsoor|race\s*course|millers|palace\s*road|queens\s*road|church\s*street|brigade\s*road|shanti\s*nagar|\bkh\s*road\b|langford|cubbon|central\s*business"),
]

NON_BLR_CITIES = r"mysuru|mysore\s+city|pune|hinjewadi|mumbai|navi\s*mumbai|noida|gurgaon|gurugram|delhi|chennai|hyderabad|kolkata|ahmedabad|coimbatore|kochi|cochin|nagpur|jaipur|thane"

CONDITION_RULES = [
    ("Bare Shell", r"bare\s*shell|core\s*(&|and)\s*shell|shell\s*(&|and)\s*core|cold\s*shell"),
    ("Warm Shell", r"warm\s*shell|wram\s*shell|semi\s*fitted"),
    ("Pre - Furnished", r"pre[\s\-]*furnish|previously\s*furnish|ready\s*fit\s*out|existing\s*fit\s*out|as[\s\-]*is\s*furnish"),
    ("Fully Furnished", r"fully\s*furnish|plug\s*(and|&|n)\s*play|furnished|turn[\s\-]*key|ready\s*to\s*move"),
    ("Managed Office", r"managed\s*(office|space|workspace)|serviced\s*office|co[\s\-]*working|flex\s*space"),
    ("BTS", r"\bbts\b|built[\s\-]*to[\s\-]*suit"),
]

DEVELOPER_OVERRIDES = {
    "sattva group (salarpuria sattva)": "Sattva Group",
    "k raheja corp (cignus)": "K Raheja Corp",
    "dnr altitude (hines.com)": "DNR Altitude",
    "capita land investment": "CapitaLand Investment",
    "indraprastha shelters pvt. ltd": "Indraprastha Shelters",
    "indospace_south": "Indospace",
    "99 tech park - hsr extension": "99 Tech Park",
    "park square whitefield": "Park Square",
    "prestige bangalore office": "Prestige Group",
    "puravankara commercial": "Puravankara",
    "sobha limited": "Sobha",
    "skav group": "Skav",
    "bagmane group": "Bagmane",
    "phoenix mills": "Phoenix Mills",
    "century real estate": "Century Real Estate",
    "featherlite developers": "Featherlite Developers",
    "gopalan enterprises": "Gopalan Enterprises",
    "nitesh estates": "Nitesh Estates",
    "slk green group corporate real estate & infrastructure arm  amin properties llp": "SLK Green Group",
}

# Top-level folders that name a location, not a landlord - the developer is the subfolder.
LOCATION_FOLDERS = {"e-city"}


def canonical_developer(folder_parts):
    """folder_parts: path segments below the supply root, e.g. ['E-City','Harita IT Park E-City']."""
    top = folder_parts[0] if folder_parts else "Unknown"
    if top.strip().lower() in LOCATION_FOLDERS and len(folder_parts) > 1:
        name = folder_parts[1]
        name = re.sub(r"\s*[-–]?\s*e[\s\-]*city\s*$", "", name, flags=re.I).strip()
        return name or top
    key = top.strip().lower()
    if key in DEVELOPER_OVERRIDES:
        return DEVELOPER_OVERRIDES[key]
    cleaned = re.sub(r"\s*\([^)]*\)\s*", " ", top).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned or top


def indian_format(value):
    """1234567 -> '12,34,567' (Indian digit grouping, as used throughout the target sheet)."""
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return ""
    sign = "-" if number < 0 else ""
    digits = str(abs(number))
    if len(digits) <= 3:
        return sign + digits
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return sign + ",".join(groups) + "," + tail


def sft(value):
    """Format an area the way the Master File does: '1,99,916 Sft'."""
    formatted = indian_format(value)
    return formatted + " Sft" if formatted else ""


def to_number(value):
    """Parse '1,26,408 Sqft', '1.1 Mn', '4.5 lakh', 45000.0 -> float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower().replace(",", "")
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    number = float(match.group(1))
    if re.search(r"\bmn\b|million|\bmillion\b", text):
        number *= 1_000_000
    elif re.search(r"lakh|lacs?|\blac\b", text):
        number *= 100_000
    elif re.search(r"\bk\b(?!va)", text) and number < 1000:
        number *= 1000
    return number


def normalize_micromarket(*texts):
    """Map any locality text onto the fixed micro-market list."""
    blob = " ".join(str(t) for t in texts if t).lower()
    if not blob.strip():
        return ""
    for label, pattern in MICROMARKET_RULES:
        if re.search(pattern, blob, re.I):
            return label
    if re.search(NON_BLR_CITIES, blob, re.I):
        return "Outside BLR"
    return "Others"


def is_bangalore(city, locality, building_name=""):
    blob = " ".join(str(t) for t in (city, locality, building_name) if t).lower()
    if re.search(r"bengaluru|bangalore|blr", blob):
        return True
    if re.search(NON_BLR_CITIES, blob):
        return False
    return True  # the corpus is a Bangalore supply set; default to in-scope


def normalize_condition(condition, detail=None):
    blob = " ".join(str(t) for t in (condition, detail) if t)
    if not blob.strip():
        return ""
    for label, pattern in CONDITION_RULES:
        if re.search(pattern, blob, re.I):
            return label
    return str(condition).strip() if condition else ""


_MONTH_ABBR = {
    "jan": "Jan", "feb": "Feb", "mar": "Mar", "apr": "Apr", "may": "May", "jun": "Jun",
    "jul": "Jul", "aug": "Aug", "sep": "Sep", "oct": "Oct", "nov": "Nov", "dec": "Dec",
}


def normalize_timeline(timeline, occupancy=None):
    """Master File uses 'Occupied', 'Immediate', or a stated future date."""
    if occupancy == "occupied":
        return "Occupied"
    text = (str(timeline).strip() if timeline else "")
    if not text:
        return "Immediate" if occupancy == "available" else ""
    low = text.lower()
    if re.search(r"occupied|leased|let\s*out|not\s*available|taken", low):
        return "Occupied"
    if re.search(r"immediate|ready|available\s*now|rto|ready\s*to\s*occupy|vacant|hand\s*over\s*done", low):
        return "Immediate"
    quarter = re.search(r"\bq([1-4])[\s\-']*(20\d{2}|\d{2})\b", low)
    if quarter:
        year = quarter.group(2)
        year = year if len(year) == 4 else "20" + year
        return "Q%s %s" % (quarter.group(1), year)
    month = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s\-']*(20\d{2}|\d{2})\b", low)
    if month:
        year = month.group(2)
        year = year if len(year) == 4 else "20" + year
        return "%s %s" % (_MONTH_ABBR[month.group(1)], year)
    return text


_ORDINAL = re.compile(r"^\s*(\d+)\s*(st|nd|rd|th)?\s*(floor|flr|f)\s*$", re.I)


def normalize_floor(label):
    """'Ground Floor' -> 'GF', '5th Floor' -> '5F', 'Level 12' -> '12F'."""
    if label is None:
        return ""
    text = str(label).strip()
    if not text:
        return ""
    low = text.lower()
    if re.fullmatch(r"(g|gf|ground(\s*floor)?)", low):
        return "GF"
    if re.fullmatch(r"(ug|upper\s*ground(\s*floor)?)", low):
        return "UGF"
    if re.fullmatch(r"(mezz(anine)?(\s*floor)?)", low):
        return "Mezzanine"
    basement = re.fullmatch(r"(b|basement)\s*[-]?\s*(\d+)?", low)
    if basement:
        return "B" + (basement.group(2) or "1")
    match = _ORDINAL.fullmatch(text) or re.fullmatch(r"\s*(?:level|lvl|floor)\s*(\d+)\s*", text, re.I)
    if match:
        return match.group(1) + "F"
    if re.fullmatch(r"\d+\s*f", low.replace(" ", "")):
        return low.replace(" ", "").upper()
    if re.fullmatch(r"\d+", low):
        return low + "F"
    return text


def normalize_structure(structure):
    """'2B+G+19' -> '2B + G + 19', matching the reference sheet's spacing."""
    if not structure:
        return ""
    text = re.sub(r"\s*\+\s*", " + ", str(structure).strip())
    return re.sub(r"\s{2,}", " ", text)


def clean_name(text):
    if not text:
        return ""
    return re.sub(r"\s{2,}", " ", str(text).replace("\n", " ").strip(" -–|\t"))
