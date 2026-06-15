"""
Rule-based event tagger. Generates a rich `tags` list from event fields.
No LLM — pure regex patterns over title + description + venue + category.
Tags are designed to match natural search terms a parent would type.
"""

import re
from datetime import datetime, timezone

# Shared adult-noise filter — import this in every scraper
ADULT_NOISE = re.compile(
    r"\b("
    # Substances / alcohol-focused events
    r"wine\s*tasting|beer\s*tasting|cocktail|happy\s*hour|bar\s*crawl|nightclub|brewery|"
    r"beer[\s,/&]+wine|wine[\s,/&]+beer|beer\s*garden|wine\s*garden|"
    r"\$\d+\s*beer|\bcraft\s*beer\b|50\+\s*tast|"
    r"winery|distillery|whiskey|whisky|spirits\s*tasting|alcohol|21\+|"
    # Adult-only events
    r"adults?\s*only|bachelorette|bachelor\s*party|strip\s*club|comedy\s*show|"
    r"stand[\s-]?up\s*comedy|open\s*mic|karaoke|speed\s*dating|singles|"
    # Financial / legal / professional
    r"estate\s*planning|living\s*trust|financial\s*planning|financial\s*literacy\s*(?!.*teen)|"
    r"wealth\s*management|investment\s*seminar|tax\s*planning|mortgage|insurance\s*seminar|"
    r"capital\s*gains|inheritance\s*planning|legal\s*seminar|divorce|retirement\s*planning|"
    r"real\s*estate\s*invest|crypto\s*invest|"
    # Networking / career
    r"networking\s*event|job\s*fair|career\s*fair|resume\s*workshop|linkedin|"
    r"professional\s*development|b2b|"
    # Explicitly adult
    r"21\s*and\s*over|18\+|over\s*21|adults?\s*only|mature\s*audience"
    r")\b",
    re.IGNORECASE,
)

# Each entry: (tag, [patterns that trigger it])
# Patterns match against a combined lowercase string of title + venue + description + category
TAG_RULES = [
    # ── Setting / environment ──────────────────────────────────────────────
    ("outdoors",        [r"\b(outdoor|outside|park|trail|garden|farm|beach|nature|hike|hiking|forest|lawn|plaza|open[\s-]air|creek|bay|lake|pond)\b"]),
    ("indoors",         [r"\b(museum|library|theatre|theater|center|hall|studio|gallery|indoor|classroom|auditorium)\b"]),
    ("water",           [r"\b(beach|pool|splash|aquatic|lake|creek|river|sand|ocean|water[\s-]play|splash\s*pad)\b"]),
    ("farm",            [r"\b(farm|barn|petting\s*zoo|livestock|chickens?|goats?|cows?|pigs?|horses?|hayride|pick[- ]your[\s-]own)\b"]),
    ("nature",          [r"\b(nature|wildlife|wild|bird|butterfly|insect|plant|trail|hike|ecology|environment|garden|outdoor)\b"]),

    # ── Activity type ──────────────────────────────────────────────────────
    ("storytime",       [r"\b(storytime|story[\s-]time|read[\s-]aloud|picture\s*book|nursery\s*rhyme|lap\s*sit)\b"]),
    ("arts & crafts",   [r"\b(art|craft|crafts|make|create|draw|paint|drawing|painting|sculpt|collage|pottery|clay|sewing|knit|weave|printmak|build|lego)\b"]),
    ("music",           [r"\b(music|concert|band|sing|song|dance|choir|orchestra|instrument|rhythm|drum|guitar|violin|musical|performance)\b"]),
    ("science",         [r"\b(science|stem|engineering|experiment|maker|robot|code|coding|chemistry|physics|astronomy|space|tech|technology|inventor|invention|innovation)\b"]),
    ("hands-on",        [r"\b(workshop|hands[\s-]on|interactive|make|build|create|experiment|activity|activities|project|maker|tinker|diy)\b"]),
    ("sensory",         [r"\b(sensory|tactile|touch|texture|messy\s*play|sand|water\s*play|slime|kinetic)\b"]),
    ("animals",         [r"\b(animal|zoo|petting|wildlife|bird|butterfly|insect|reptile|fish|mammal|creature|nature|farm|flamingo|penguin|aquarium)\b"]),
    ("theatre",         [r"\b(theatre|theater|show|performance|play|puppet|puppetry|stage|acting|improv|drama|musical|circus|magic|magician)\b"]),
    ("festival",        [r"\b(festival|fair|carnival|expo|celebration|parade|fiesta|feria|market|faire)\b"]),
    ("film & movies",   [r"\b(movie|film|cinema|screening|outdoor\s*movie|movie\s*night|drive[\s-]in)\b"]),
    ("sports & movement",[r"\b(soccer|baseball|basketball|swim|climb|gym|sport|yoga|movement|run|race|obstacle|martial\s*arts|karate|dance|tumbl|gymnastics|parkour)\b"]),
    ("cooking",         [r"\b(cook|bake|food|kitchen|recipe|chef|culinary|taste|snack)\b"]),
    ("books & reading", [r"\b(storytime|read[\s-]aloud|picture\s*book|author|library|literature|poetry|poem)\b"]),
    ("STEM",            [r"\b(stem|science|technology|engineering|math|robot|code|coding|programming|computer|3d\s*print)\b"]),

    # ── Vibe / practical ──────────────────────────────────────────────────
    ("free",            [r"^.*$"]),          # applied conditionally below
    ("drop-in",         [r"\b(walk[\s-]?up|drop[\s-]?in|no\s*registration|no\s*ticket|free\s*admission|open\s*to\s*all)\b"]),
    ("book ahead",      [r"\b(register|registration|ticket|reserve|reservation|sell[\s-]?out|selling\s*out|capacity|limited\s*space|sign[\s-]?up)\b"]),
    ("rainy day",       [r"\b(indoor|museum|library|theatre|theater|center|hall|studio|gallery|classroom|auditorium)\b"]),
    ("toddler-friendly",[r"\b(toddler|baby|babies|infant|0[\s-]?to[\s-]?3|1[\s-]?to[\s-]?3|lap[\s-]sit|little\s*one|little\s*ones|tiny|family|stroller[\s-]?friendly)\b"]),
    ("preschool",       [r"\b(preschool|pre[\s-]k|pre[\s-]school|3[\s-]5\s*(years?|yrs?)|ages?\s*[23]|ages?\s*3[\s-]5)\b"]),
    ("school-age",      [r"\b(school[\s-]age|elementary|ages?\s*[5-9]|kids|children|tween|grade)\b"]),
    ("all ages",        [r"\b(all\s*ages|family[\s-]friendly|everyone|whole\s*family|open\s*to\s*all)\b"]),

    # ── Location shortcuts ─────────────────────────────────────────────────
    ("palo alto",       [r"\b(palo\s*alto|junior\s*museum|cantor|stanford)\b"]),
    ("san francisco",   [r"\b(san\s*francisco|\bsf\b|golden\s*gate|mission|soma|presidio|marin\b)\b"]),
    ("east bay",        [r"\b(east\s*bay|oakland|berkeley|alameda|fremont|hayward|contra\s*costa|livermore|walnut\s*creek|danville)\b"]),
    ("peninsula",       [r"\b(peninsula|menlo\s*park|redwood\s*city|san\s*mateo|burlingame|foster\s*city|san\s*carlos|belmont|half\s*moon)\b"]),

    # ── Seasonal / occasion ────────────────────────────────────────────────
    ("summer",          [r"\b(summer|june|july|august|pool|splash|outdoor|beach|camp)\b"]),
    ("weekend",         []),                 # applied conditionally below
    ("weekday",         []),                 # applied conditionally below
]

# Patterns that mark event as likely kid/family-relevant (used as quality signal, not a tag)
_KID_SIGNAL = re.compile(
    r"\b(child|children|kids?|family|families|toddler|baby|babies|infant|storytime|preschool|"
    r"pre-?k|tween|youth|junior|playground|school|learning|creative)\b",
    re.IGNORECASE,
)


def _compile(patterns):
    if not patterns:
        return None
    return re.compile("|".join(patterns), re.IGNORECASE)


_COMPILED = [(tag, _compile(pats)) for tag, pats in TAG_RULES]


def tag_event(event: dict) -> list[str]:
    """Return a deduplicated list of tags for an event."""
    # Build haystack from all text fields
    haystack = " ".join(filter(None, [
        event.get("title", ""),
        event.get("venue", ""),
        event.get("city", ""),
        event.get("age_range", ""),
        event.get("category", ""),
        event.get("source_name", ""),
        event.get("ticket_status", ""),
    ])).lower()

    tags = set()

    for tag, pattern in _COMPILED:
        # Conditional tags
        if tag == "free":
            if event.get("cost") == "Free":
                tags.add("free")
            continue
        if tag == "weekend":
            dt_str = event.get("start_datetime", "")
            if dt_str:
                try:
                    dt = datetime.fromisoformat(dt_str)
                    if dt.weekday() in (5, 6):
                        tags.add("weekend")
                    else:
                        tags.add("weekday")
                except Exception:
                    pass
            continue
        if tag == "weekday":
            continue  # handled above

        if pattern and pattern.search(haystack):
            tags.add(tag)

    # Ensure "outdoors" and "rainy day" don't both appear — outdoors wins
    if "outdoors" in tags:
        tags.discard("rainy day")

    # Always include the source channel as a tag
    ch = event.get("source_channel", "")
    if ch:
        tags.add(ch)

    return sorted(tags)


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
    """
    Returns one of: 'babies', 'toddlers', 'preschool', 'kids', 'teens', 'family', or '' (unknown).
    Priority: explicit numeric range > keyword signals.
    """
    haystack = " ".join(filter(None, [
        event.get("title", ""),
        event.get("age_range", ""),
        event.get("venue", ""),
    ]))

    # Numeric age range: classify by midpoint
    m = _AGE_RANGE_NUM.search(haystack)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        mid = (lo + hi) / 2
        if hi <= 2:
            return "babies"
        if hi <= 4 and lo <= 2:
            return "toddlers"
        if hi <= 6 and lo <= 4:
            return "preschool"
        if lo >= 12:
            return "teens"
        if mid <= 8:
            return "kids"
        return "kids"

    # Keyword signals (order matters — most specific first)
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
    return "family"  # default: broadly family-appropriate


def enrich_title(event: dict) -> str:
    """
    For venue events where the title is generic (doesn't mention the venue),
    prepend the venue name so titles are self-explanatory.
    """
    title = event.get("title", "")
    venue = event.get("source_name", "") or event.get("venue", "")

    if event.get("source_channel") != "venue":
        return title

    # If venue name already appears in title, leave it
    venue_short = venue.split("—")[0].strip().split(" ")[0].lower()
    if venue_short and venue_short in title.lower():
        return title

    # Generic titles that don't self-identify
    GENERIC = re.compile(
        r"^(today[’']?s?\s+schedule|open|hours|general\s+admission|visit|"
        r"drop[\s-]?in|walk[\s-]?in|open\s+house|weekend\s+open|daily\s+program)",
        re.IGNORECASE,
    )
    if GENERIC.match(title.strip()):
        return f"{venue} — {title}"

    return title
