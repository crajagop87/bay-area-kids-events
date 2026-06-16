"""
LibCal ICS scraper for libraries that publish public iCal feeds.
Currently covers: Mountain View Public Library (cid=8800).

Each ICS feed is parsed using the icalendar library and filtered
to kids/family-relevant events within the requested time window.
"""

import hashlib
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")

import requests

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (compatible; BayAreaKidsEvents/1.0; "
    "+https://github.com/crajagop87/bay-area-kids-events)"
)
HEADERS = {"User-Agent": UA}

MULTI_WEEK_CAMP = re.compile(
    r"\b(summer\s*camp|week[\-\s]?long\s*camp|multi[\-\s]?week)\b", re.IGNORECASE
)

# Keywords that indicate kids/family relevance
KIDS_KEYWORDS = re.compile(
    r"\b(kid|child|children|youth|teen|toddler|baby|infant|junior|family|"
    r"storytime|story\s*time|craft|art|music|stem|lego|game|camp|"
    r"summer\s*reading|school.age|preschool|kindergarten|puppet|"
    r"bilingual|draw|sing|dance|make|explore|learn)\b",
    re.IGNORECASE,
)

# Categories that signal kids content
KIDS_CATEGORIES = re.compile(
    r"\b(youth|kids?|children|families?|storytime|teens?|juvenile|"
    r"junior|summer\s*reading|amplify)\b",
    re.IGNORECASE,
)

# Adult-only noise terms to filter out
ADULT_NOISE = re.compile(
    r"\b(adult|senior|genealogy|ESL|citizenship|knit|needle\s*craft|"
    r"board\s*of\s*trustee|book\s*club\s+for\s+adult|wine|beer)\b",
    re.IGNORECASE,
)

# Libraries using LibCal ICS feeds
LIBCAL_SOURCES = [
    {
        "name": "Mountain View Public Library",
        "source_id": "mvpl",
        "ics_url": "https://mountainview.libcal.com/ical_subscribe.php?cid=8800",
        "city": "Mountain View",
        "county": "Santa Clara",
        "lat": 37.3893,
        "lng": -122.0819,
    },
]


def _dedupe_key(title: str, date_str: str, city: str) -> str:
    raw = f"{title.lower().strip()}|{date_str}|{city.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _is_kids_relevant(summary: str, description: str, categories: str) -> bool:
    """Return True if event is likely kids/family relevant."""
    combined = f"{summary} {description} {categories}"
    # Explicit adult-only keywords → skip
    if ADULT_NOISE.search(summary):
        return False
    # Positive kids signal
    if KIDS_KEYWORDS.search(combined):
        return True
    if KIDS_CATEGORIES.search(categories):
        return True
    return False


def _parse_ics_text(ics_text: str) -> list[dict]:
    """Parse raw ICS text using icalendar library and return list of component dicts."""
    try:
        from icalendar import Calendar
    except ImportError:
        log.error("icalendar library not installed — run: pip install icalendar")
        return []

    try:
        cal = Calendar.from_ical(ics_text)
    except Exception as exc:
        log.error("Failed to parse ICS: %s", exc)
        return []

    components = []
    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        summary = str(component.get("SUMMARY", "")).strip()
        description = str(component.get("DESCRIPTION", "")).strip()
        categories_raw = component.get("CATEGORIES")
        if categories_raw:
            if hasattr(categories_raw, "cats"):
                categories = ", ".join(str(c) for c in categories_raw.cats)
            else:
                categories = str(categories_raw)
        else:
            categories = ""
        url = str(component.get("URL", "")).strip()
        location = str(component.get("LOCATION", "")).strip()

        dtstart = component.get("DTSTART")
        dtend = component.get("DTEND")

        start_dt = None
        end_dt = None
        if dtstart:
            val = dtstart.dt
            if hasattr(val, "hour"):
                if val.tzinfo is None:
                    val = val.replace(tzinfo=PACIFIC)
                # Convert to Pacific so fmt_time (which reads raw hours) shows local time.
                # All other scrapers store local PT hours with a dummy +00:00 suffix;
                # we follow the same convention so display is consistent.
                val_pt = val.astimezone(PACIFIC)
                start_dt = val_pt.replace(tzinfo=timezone.utc)
            else:
                start_dt = datetime(val.year, val.month, val.day, tzinfo=timezone.utc)

        if dtend:
            val = dtend.dt
            if hasattr(val, "hour"):
                if val.tzinfo is None:
                    val = val.replace(tzinfo=PACIFIC)
                val_pt = val.astimezone(PACIFIC)
                end_dt = val_pt.replace(tzinfo=timezone.utc)
            else:
                end_dt = datetime(val.year, val.month, val.day, tzinfo=timezone.utc)

        components.append({
            "summary": summary,
            "description": description,
            "categories": categories,
            "url": url,
            "location": location,
            "start_dt": start_dt,
            "end_dt": end_dt,
        })

    return components


def _scrape_one(source: dict, window_days: int) -> tuple[list[dict], dict]:
    """Fetch and parse one LibCal ICS feed."""
    name = source["name"]
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=window_days)

    try:
        resp = requests.get(source["ics_url"], headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as exc:
        log.warning("LibCal ICS fetch failed for %s: %s", name, exc)
        return [], {"source": name, "status": "error", "error": str(exc), "count": 0}

    if "VCALENDAR" not in resp.text:
        log.warning("LibCal ICS for %s returned non-calendar content", name)
        return [], {"source": name, "status": "error", "error": "not a VCALENDAR", "count": 0}

    components = _parse_ics_text(resp.text)
    events = []

    for comp in components:
        summary = comp["summary"]
        if not summary:
            continue
        start_dt = comp["start_dt"]
        end_dt = comp["end_dt"]

        # Filter to time window
        if start_dt:
            if start_dt < now or start_dt > cutoff:
                continue

        # Filter to kids/family content
        if not _is_kids_relevant(summary, comp["description"], comp["categories"]):
            continue

        date_str = start_dt.date().isoformat() if start_dt else ""
        is_camp = bool(MULTI_WEEK_CAMP.search(summary))

        # Infer cost from description
        desc_lower = comp["description"].lower()
        if "free" in desc_lower or not any(c in desc_lower for c in ["$", "fee", "cost", "ticket"]):
            cost_label = "Free"
            cost_amt = 0.0
        else:
            cost_label = "Paid"
            cost_amt = 0.0
            m = re.search(r"\$\s*([\d,.]+)", comp["description"])
            if m:
                cost_amt = float(m.group(1).replace(",", ""))

        event = {
            "title": summary,
            "start_datetime": start_dt.isoformat() if start_dt else None,
            "end_datetime": end_dt.isoformat() if end_dt else None,
            "venue": comp["location"] or source["name"],
            "city": source["city"],
            "county": source["county"],
            "lat": source["lat"],
            "lng": source["lng"],
            "age_range": "Families",
            "cost": cost_label,
            "cost_amount": cost_amt,
            "ticket_status": "book ahead" if cost_amt > 0 else "free walk-up",
            "ticket_url": comp["url"],
            "category": "camp" if is_camp else "library",
            "source_channel": "library",
            "source_name": source["source_id"],
            "source_url": comp["url"] or source["ics_url"],
            "last_verified": now.isoformat(),
            "dedupe_key": _dedupe_key(summary, date_str, source["city"]),
            "is_camp": is_camp,
        }
        events.append(event)

    health = {
        "source": name,
        "status": "ok",
        "count": len(events),
    }
    log.info("LibCal ICS %s: %d kids events (of %d total)", name, len(events), len(components))
    return events, health


def scrape_all_libcal_ics(window_days: int = 16) -> tuple[list[dict], list[dict]]:
    """Scrape all LibCal ICS sources. Returns (events, health_records)."""
    all_events: list[dict] = []
    all_health: list[dict] = []

    for i, source in enumerate(LIBCAL_SOURCES):
        if i > 0:
            time.sleep(1)
        events, health = _scrape_one(source, window_days)
        all_events.extend(events)
        all_health.append(health)

    return all_events, all_health
