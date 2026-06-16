"""
Rule-based event tagger. Generates a rich `tags` list from event fields.
No LLM — pure regex patterns over title + description + venue + category.

Tag discipline:
- Only tags in CANONICAL_TAGS may appear in output (no freeform strings).
- SYNONYM_MAP collapses common variants to canonical forms before lookup.
- Source-channel names (venue/library/etc.) are NOT exposed as tags.
"""

import re
from datetime import datetime, timezone

# Shared adult-noise filter — import this in every scraper
ADULT_NOISE = re.compile(
    r"\b("
    r"wine\s*tasting|beer\s*tasting|cocktail|happy\s*hour|bar\s*crawl|nightclub|brewery|"
    r"beer[\s,/&]+wine|wine[\s,/&]+beer|beer\s*garden|wine\s*garden|"
    r"winery|distillery|whiskey|whisky|spirits\s*tasting|alcohol|21\+|"
    r"adults?\s*only|bachelorette|bachelor\s*party|strip\s*club|comedy\s*show|"
    r"stand[\s-]?up\s*comedy|open\s*mic|karaoke|speed\s*dating|singles|"
    r"estate\s*planning|living\s*trust|financial\s*planning|financial\s*literacy\s*(?!.*teen)|"
    r"wealth\s*management|investment\s*seminar|tax\s*planning|mortgage|insurance\s*seminar|"
    r"capital\s*gains|inheritance\s*planning|legal\s*seminar|divorce|retirement\s*planning|"
    r"real\s*estate\s*invest|crypto\s*invest|"
    r"networking\s*event|job\s*fair|career\s*fair|resume\s*workshop|linkedin|"
    r"professional\s*development|b2b|"
    r"21\s*and\s*over|18\+|over\s*21|mature\s*audience"
    r")\b",
    re.IGNORECASE,
)

# ── Canonical tag taxonomy ────────────────────────────────────────────────────
# These are the ONLY strings that may appear in event["tags"].
# Grouped for readability; order here doesn't matter for logic.

CANONICAL_TAGS: set[str] = {
    # Environment
    "outdoors", "indoors", "water play",
    # Setting
    "farm", "nature", "beach",
    # Activity
    "storytime", "arts & crafts", "music & dance", "science & STEM",
    "theatre & performance", "sports & movement", "cooking & food",
    "books & reading", "sensory play", "animals",
    "film & movies", "festival & fair", "food & drink",
    # Vibe / logistics
    "free", "drop-in", "book ahead", "rainy day",
    # Age shorthand
    "toddler-friendly", "all ages",
    # Time
    "weekend", "weekday", "summer",
    # Location
    "palo alto", "san francisco", "east bay", "peninsula", "south bay",
}

# Synonyms → canonical.  Add new variants here as they appear in source data.
SYNONYM_MAP: dict[str, str] = {
    # Activity duplicates
    "science":           "science & STEM",
    "STEM":              "science & STEM",
    "stem":              "science & STEM",
    "arts and crafts":   "arts & crafts",
    "craft":             "arts & crafts",
    "crafts":            "arts & crafts",
    "music":             "music & dance",
    "dance":             "music & dance",
    "theater":           "theatre & performance",
    "theatre":           "theatre & performance",
    "performance":       "theatre & performance",
    "puppet":            "theatre & performance",
    "cooking":           "cooking & food",
    "baking":            "cooking & food",
    "food":              "cooking & food",
    "sports":            "sports & movement",
    "movement":          "sports & movement",
    "exercise":          "sports & movement",
    "water":             "water play",
    "splash":            "water play",
    "pool":              "water play",
    "festival":          "festival & fair",
    "fair":              "festival & fair",
    "carnival":          "festival & fair",
    "hands-on":          "arts & crafts",   # usually craft/make context
    "hands on":          "arts & crafts",
    "school-age":        "all ages",         # too narrow to be useful as tag
    "preschool":         "toddler-friendly", # close enough in practice
    # Food specifics → food & drink
    "ice cream":         "food & drink",
    "dessert":           "food & drink",
    "snack":             "food & drink",
    "taste":             "food & drink",
    "tasting":           "food & drink",
    # Location variants
    "sf":                "san francisco",
    "the city":          "san francisco",
    "south bay":         "south bay",
    "silicon valley":    "south bay",
}

# ── Tag rules: (canonical_tag, [regex patterns]) ──────────────────────────────
# Patterns match the full lowercase haystack (title + venue + city + etc.)

TAG_RULES: list[tuple[str, list[str]]] = [
    # Environment
    ("outdoors",              [r"\b(outdoor|outside|park|trail|garden|farm|beach|nature|hike|hiking|forest|lawn|plaza|open[\s-]air|creek|bay|lake|pond)\b"]),
    ("indoors",               [r"\b(museum|library|theatre|theater|center|hall|studio|gallery|indoor|classroom|auditorium)\b"]),
    ("water play",            [r"\b(beach|pool|splash|aquatic|lake|creek|river|sand|ocean|water[\s-]play|splash\s*pad|swim)\b"]),
    ("farm",                  [r"\b(farm|barn|petting\s*zoo|livestock|chickens?|goats?|cows?|pigs?|horses?|hayride|pick[- ]your[\s-]own)\b"]),
    ("nature",                [r"\b(nature|wildlife|wild|bird|butterfly|insect|plant|trail|hike|ecology|environment)\b"]),
    ("beach",                 [r"\b(beach|ocean|shore|sand|surf|coastal)\b"]),

    # Activity
    ("storytime",             [r"\b(storytime|story[\s-]time|read[\s-]aloud|picture\s*book|nursery\s*rhyme|lap\s*sit|lapsit)\b"]),
    ("arts & crafts",         [r"\b(art|craft|crafts|make|create|draw|paint|drawing|painting|sculpt|collage|pottery|clay|sewing|weave|printmak|lego|build)\b"]),
    ("music & dance",         [r"\b(music|concert|band|sing|song|dance|choir|orchestra|instrument|rhythm|drum|guitar|violin|musical)\b"]),
    ("science & STEM",        [r"\b(science|stem|engineering|experiment|maker|robot|code|coding|chemistry|physics|astronomy|space|tech|technology|inventor|innovation|math|3d\s*print|computer)\b"]),
    ("theatre & performance", [r"\b(theatre|theater|show|performance|play|puppet|puppetry|stage|acting|improv|drama|musical|circus|magic|magician)\b"]),
    ("sports & movement",     [r"\b(soccer|baseball|basketball|swim|climb|gym|sport|yoga|movement|run|race|obstacle|martial\s*arts|karate|tumbl|gymnastics|parkour|fitness)\b"]),
    ("cooking & food",        [r"\b(cook|bake|kitchen|recipe|chef|culinary)\b"]),
    ("food & drink",          [r"\b(ice\s*cream|dessert|snack|tasting|food\s*truck|farmers?\s*market|taste|gelato|pastry|donut|doughnut|pizza|cupcake)\b"]),
    ("books & reading",       [r"\b(read[\s-]aloud|picture\s*book|author|literature|poetry|poem|book\s*club|reading\s*program|summer\s*reading)\b"]),
    ("sensory play",          [r"\b(sensory|tactile|touch|texture|messy\s*play|slime|kinetic|sand\s*play)\b"]),
    ("animals",               [r"\b(animal|zoo|petting|wildlife|bird|butterfly|insect|reptile|fish|mammal|creature|farm|flamingo|penguin|aquarium|horse|goat|chicken|cow)\b"]),
    ("theatre & performance", [r"\b(theatre|theater|show|performance|play|puppet|stage|drama|circus|magic)\b"]),
    ("film & movies",         [r"\b(movie|film|cinema|screening|outdoor\s*movie|movie\s*night|drive[\s-]in)\b"]),
    ("festival & fair",       [r"\b(festival|fair|carnival|expo|celebration|parade|fiesta|feria|market|faire)\b"]),

    # Vibe / logistics
    ("free",                  []),  # applied conditionally
    ("drop-in",               [r"\b(walk[\s-]?up|drop[\s-]?in|no\s*registration|free\s*admission|open\s*to\s*all)\b"]),
    ("book ahead",            [r"\b(register|registration|ticket|reserve|reservation|limited\s*space|sign[\s-]?up|selling\s*out)\b"]),
    ("rainy day",             [r"\b(indoor|museum|library|theatre|theater|center|hall|studio|gallery|classroom|auditorium)\b"]),
    ("toddler-friendly",      [r"\b(toddler|baby|babies|infant|0[\s-]?to[\s-]?3|1[\s-]?to[\s-]?3|lap[\s-]sit|lapsit|little\s*one|stroller[\s-]?friendly|preschool|pre[\s-]k)\b"]),
    ("all ages",              [r"\b(all\s*ages|family[\s-]friendly|everyone|whole\s*family|open\s*to\s*all|every\s*age)\b"]),

    # Location
    ("palo alto",             [r"\b(palo\s*alto|junior\s*museum|cantor|stanford)\b"]),
    ("san francisco",         [r"\b(san\s*francisco|\bsf\b|golden\s*gate|mission|soma|presidio)\b"]),
    ("east bay",              [r"\b(east\s*bay|oakland|berkeley|alameda|fremont|hayward|contra\s*costa|livermore|walnut\s*creek|danville)\b"]),
    ("peninsula",             [r"\b(peninsula|menlo\s*park|redwood\s*city|san\s*mateo|burlingame|foster\s*city|san\s*carlos|belmont|half\s*moon)\b"]),
    ("south bay",             [r"\b(san\s*jose|sunnyvale|santa\s*clara|cupertino|mountain\s*view|los\s*altos|milpitas|campbell|saratoga|los\s*gatos)\b"]),

    # Seasonal
    ("summer",                [r"\b(summer|june|july|august|camp)\b"]),
    ("weekend",               []),  # applied conditionally
    ("weekday",               []),  # applied conditionally
]


def _compile(patterns: list[str]):
    if not patterns:
        return None
    return re.compile("|".join(patterns), re.IGNORECASE)


_COMPILED: list[tuple[str, object]] = [(tag, _compile(pats)) for tag, pats in TAG_RULES]


def _canonicalize(tag: str):
    """Normalize a tag to its canonical form, or return None if not allowed."""
    if tag in CANONICAL_TAGS:
        return tag
    mapped = SYNONYM_MAP.get(tag) or SYNONYM_MAP.get(tag.lower())
    if mapped and mapped in CANONICAL_TAGS:
        return mapped
    return None


def tag_event(event: dict) -> list[str]:
    """Return a sorted, deduplicated list of canonical tags for an event."""
    haystack = " ".join(filter(None, [
        event.get("title", ""),
        event.get("venue", ""),
        event.get("city", ""),
        event.get("age_range", ""),
        event.get("category", ""),
        event.get("source_name", ""),
        event.get("ticket_status", ""),
    ])).lower()

    tags: set[str] = set()

    for tag, pattern in _COMPILED:
        if tag == "free":
            if event.get("cost") == "Free":
                tags.add("free")
            continue
        if tag == "weekend":
            dt_str = event.get("start_datetime", "")
            if dt_str:
                try:
                    from zoneinfo import ZoneInfo
                    dt = datetime.fromisoformat(dt_str).astimezone(ZoneInfo("America/Los_Angeles"))
                    tags.add("weekend" if dt.weekday() in (5, 6) else "weekday")
                except Exception:
                    pass
            continue
        if tag == "weekday":
            continue  # handled in weekend branch

        if pattern and pattern.search(haystack):
            canonical = _canonicalize(tag)
            if canonical:
                tags.add(canonical)

    # outdoors beats rainy day
    if "outdoors" in tags:
        tags.discard("rainy day")

    # Validate every tag is canonical (safety net)
    tags = {t for t in tags if t in CANONICAL_TAGS}

    return sorted(tags)


# ── Age group inference ───────────────────────────────────────────────────────

_AGE_BABY = re.compile(
    r"\b(baby|babies|infant|lapsit|lap[\s-]sit|0[\s-]?to[\s-]?[12]|ages?\s*0|newborn|birth[\s-]?to)\b",
    re.IGNORECASE,
)
_AGE_TODDLER = re.compile(
    r"\b(toddler|tiny\s*tot|little\s*one|1[\s-]?to[\s-]?3|2[\s-]?to[\s-]?4|ages?\s*[123](\b|[\s-]?(and|to|&)[\s-]?[234])|"
    r"pre[\s-]?walker|waddler|crawler)\b",
    re.IGNORECASE,
)
_AGE_PRESCHOOL = re.compile(
    r"\b(preschool|pre[\s-]?k|pre[\s-]?school|ages?\s*[34][\s-]?(?:to|and|&|-)[\s-]?[56]|"
    r"ages?\s*3[\s-]5|ages?\s*4[\s-]6|[34][\s-]?year[\s-]?old)\b",
    re.IGNORECASE,
)
_AGE_TEEN = re.compile(
    r"\b(teen|tween|youth\s*group|middle\s*school|high\s*school|ages?\s*1[2-9]|"
    r"ages?\s*13[\s-]?(?:to|and|&|-)?\s*1[89]|gr(?:ade)?s?\s*[6-9]|grades?\s*(?:six|seven|eight|nine|ten|eleven|twelve))\b",
    re.IGNORECASE,
)
_AGE_KIDS = re.compile(
    r"\b(kids?|children|child|elementary|school[\s-]age|ages?\s*[5-9]|ages?\s*[5-9]\s*(?:to|and|&|-)\s*1[012]|"
    r"gr(?:ade)?s?\s*[1-5]|grades?\s*(?:one|two|three|four|five)|after[\s-]school)\b",
    re.IGNORECASE,
)
_AGE_FAMILY = re.compile(
    r"\b(family|families|all\s*ages|kids\s*and\s*adults?|everyone|whole\s*family|open\s*to\s*all)\b",
    re.IGNORECASE,
)
_AGE_RANGE_NUM = re.compile(
    r"\bages?\s*(\d+)\s*(?:to|and|&|[-–])\s*(\d+)\b",
    re.IGNORECASE,
)


def infer_age_group(event: dict) -> str:
    haystack = " ".join(filter(None, [
        event.get("title", ""),
        event.get("age_range", ""),
        event.get("venue", ""),
    ]))

    m = _AGE_RANGE_NUM.search(haystack)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if hi <= 2:
            return "babies"
        if hi <= 4 and lo <= 2:
            return "toddlers"
        if hi <= 6 and lo <= 4:
            return "preschool"
        if lo >= 12:
            return "teens"
        return "kids"

    if _AGE_BABY.search(haystack):
        return "babies"
    if _AGE_TODDLER.search(haystack):
        return "toddlers"
    if _AGE_PRESCHOOL.search(haystack):
        return "preschool"
    if _AGE_TEEN.search(haystack):
        return "teens"
    if _AGE_KIDS.search(haystack):
        return "kids"
    if _AGE_FAMILY.search(haystack):
        return "family"
    return "family"


def enrich_title(event: dict) -> str:
    title = event.get("title", "")
    venue = event.get("source_name", "") or event.get("venue", "")

    if event.get("source_channel") != "venue":
        return title

    venue_short = venue.split("—")[0].strip().split(" ")[0].lower()
    if venue_short and venue_short in title.lower():
        return title

    GENERIC = re.compile(
        r"^(today['']?s?\s+schedule|open|hours|general\s+admission|visit|"
        r"drop[\s-]?in|walk[\s-]?in|open\s+house|weekend\s+open|daily\s+program)",
        re.IGNORECASE,
    )
    if GENERIC.match(title.strip()):
        return f"{venue} — {title}"

    return title
