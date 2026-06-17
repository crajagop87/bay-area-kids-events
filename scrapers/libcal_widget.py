"""
LibCal widget scraper for libraries that use the Springshare LibCal platform
but do NOT expose a valid ICS subscribe endpoint.

These libraries serve events via the LibCal mini-calendar widget
(/widget/events/minicalendar) which is publicly accessible without auth.

Covered:
- Sunnyvale Public Library  (iid=4934, cal_id=13025)
- San Mateo Public Library  (iid=4554, cal_id=12176)

robots.txt for both: no blanket Disallow for *, crawl-delay=10.
We respect the crawl-delay with time.sleep(10) between requests.
"""

import hashlib
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from typing import Optional

import requests

log = logging.getLogger(__name__)

PACIFIC = ZoneInfo("America/Los_Angeles")

UA = (
    "Mozilla/5.0 (compatible; BayAreaKidsEvents/1.0; "
    "+https://github.com/crajagop87/bay-area-kids-events)"
)
HEADERS = {"User-Agent": UA}

# Libraries using LibCal widget (no public ICS calendar feed)
LIBCAL_WIDGET_SOURCES = [
    {
        "name": "Sunnyvale Public Library",
        "source_id": "sunnyvale_pl",
        "widget_url": "https://sunnyvale.libcal.com/widget/events/minicalendar?iid=4934&cal_id=13025&l=200&tar=0",
        "base_url": "https://sunnyvale.libcal.com",
        "city": "Sunnyvale",
        "county": "Santa Clara",
        "lat": 37.3688,
        "lng": -122.0363,
    },
    {
        "name": "San Mateo Public Library",
        "source_id": "sanmateo_pl",
        "widget_url": "https://sanmateopublic.libcal.com/widget/events/minicalendar?iid=4554&cal_id=12176&l=200&tar=0",
        "base_url": "https://sanmateopublic.libcal.com",
        "city": "San Mateo",
        "county": "San Mateo",
        "lat": 37.5630,
        "lng": -122.3255,
    },
]

MULTI_WEEK_CAMP = re.compile(
    r"\b(summer\s*camp|week[\-\s]?long\s*camp|multi[\-\s]?week)\b", re.IGNORECASE
)

KIDS_KEYWORDS = re.compile(
    r"\b(kid|child|children|youth|teen|toddler|baby|infant|junior|family|"
    r"storytime|story\s*time|craft|art|music|stem|lego|game|camp|"
    r"summer\s*reading|school.age|preschool|kindergarten|puppet|"
    r"bilingual|draw|sing|dance|make|explore|learn)\b",
    re.IGNORECASE,
)

ADULT_NOISE = re.compile(
    r"\b(adult|senior|genealogy|ESL|citizenship|knit|needle\s*craft|embroidery|sewing|"
    r"board\s*of\s*trustee|book\s*club\s+for\s+adult|wine|beer|mahjong|"
    r"english\s*conversation|retirement|tax|cycling|book\s*discussion)\b",
    re.IGNORECASE,
)

# Match patterns like:
#   "11:00am - 11:30am, Tue Jun 16th 2026"   (Sunnyvale format)
#   "Wed Jun 17th 2026"                        (Sunnyvale all-day)
#   "1:00pm - 4:00pm, Tuesday, June 16, 2026" (San Mateo format)
#   "Friday, June 19, 2026"                    (San Mateo all-day)
_TIME_WITH_DATE_RE = re.compile(
    r"(?:(\d{1,2}:\d{2}[ap]m)\s*-\s*(\d{1,2}:\d{2}[ap]m),?\s*)?"
    r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|"
    r"Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+)?"
    r"(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})",
    re.IGNORECASE,
)

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4,
    "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}


def _parse_time_str(time_str: str, base_date: datetime) -> Optional[datetime]:
    """Parse a time string like '11:00am' into a datetime."""
    m = re.match(r"(\d{1,2}):(\d{2})([ap]m)", time_str.strip(), re.IGNORECASE)
    if not m:
        return None
    h, mi, ampm = int(m.group(1)), int(m.group(2)), m.group(3).lower()
    if ampm == "pm" and h != 12:
        h += 12
    if ampm == "am" and h == 12:
        h = 0
    return base_date.replace(hour=h, minute=mi, second=0, microsecond=0)


def _parse_datetime_text(dt_text: str) -> tuple:
    """Parse the mini-calendar date/time string into (start_dt, end_dt) in Pacific time.

    Input examples:
      '11:00am - 11:30am, Tue Jun 16th 2026'
      'Wed Jun 17th 2026'  (all-day)
    """
    m = _TIME_WITH_DATE_RE.search(dt_text)
    if not m:
        return None, None

    start_time_str, end_time_str, month_str, day_str, year_str = m.groups()
    month = _MONTH_MAP.get(month_str.lower()[:3])
    if not month:
        return None, None

    year = int(year_str)
    day = int(day_str)

    base = datetime(year, month, day, 0, 0, 0, tzinfo=PACIFIC)

    if start_time_str:
        start_dt = _parse_time_str(start_time_str, base)
        end_dt = _parse_time_str(end_time_str, base) if end_time_str else None
    else:
        # All-day event — use midnight
        start_dt = base
        end_dt = None

    # Convert Pacific-aware times to true UTC
    if start_dt:
        start_dt = start_dt.astimezone(timezone.utc)
    if end_dt:
        end_dt = end_dt.astimezone(timezone.utc)

    return start_dt, end_dt


def _dedupe_key(title: str, date_str: str, city: str) -> str:
    raw = f"{title.lower().strip()}|{date_str}|{city.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _parse_widget_html(html: str, source: dict, now: datetime, cutoff: datetime) -> list[dict]:
    """Parse the LibCal mini-calendar widget HTML into event dicts."""
    events = []

    # Find all <li> blocks in the event list
    li_blocks = re.findall(r"<li>(.*?)</li>", html, re.DOTALL)

    for block in li_blocks:
        # Extract title and URL
        link_m = re.search(
            r'<a href="([^"]+)"[^>]*>\s*([^<]+)\s*</a>',
            block,
            re.DOTALL,
        )
        if not link_m:
            continue

        event_url = link_m.group(1).strip()
        # Strip ?hs=a query param
        event_url = re.sub(r"\?hs=a$", "", event_url)
        title = link_m.group(2).strip()
        # Unescape common HTML entities
        title = (
            title.replace("&amp;", "&")
                 .replace("&lt;", "<")
                 .replace("&gt;", ">")
                 .replace("&quot;", '"')
                 .replace("&#039;", "'")
        )

        if not title:
            continue

        # Skip cancelled events
        if re.search(r"\bcancel", title, re.IGNORECASE):
            continue

        # Extract date/time text
        time_m = re.search(
            r'<span class="mini-date-time">\s*([^<]+)\s*</span>',
            block,
        )
        dt_text = time_m.group(1).strip() if time_m else ""

        start_dt, end_dt = _parse_datetime_text(dt_text)

        if start_dt:
            # Filter to requested time window (start_dt is already UTC after _parse_datetime_text)
            if start_dt < now or start_dt > cutoff:
                continue

        # Skip only events that are clearly adults-only
        if ADULT_NOISE.search(title):
            continue

        date_str = start_dt.date().isoformat() if start_dt else ""
        is_camp = bool(MULTI_WEEK_CAMP.search(title))

        event = {
            "title": title,
            "start_datetime": start_dt.isoformat() if start_dt else None,
            "end_datetime": end_dt.isoformat() if end_dt else None,
            "venue": source["name"],
            "city": source["city"],
            "county": source["county"],
            "lat": source["lat"],
            "lng": source["lng"],
            "age_range": "Families",
            "cost": "Free",
            "cost_amount": 0.0,
            "ticket_status": "free walk-up",
            "ticket_url": event_url,
            "category": "camp" if is_camp else "library",
            "source_channel": "library",
            "source_name": source["source_id"],
            "source_url": event_url,
            "last_verified": now.isoformat(),
            "dedupe_key": _dedupe_key(title, date_str, source["city"]),
            "is_camp": is_camp,
        }
        events.append(event)

    return events


def _scrape_one(source: dict, window_days: int) -> tuple[list[dict], dict]:
    """Fetch and parse one LibCal widget source."""
    name = source["name"]
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=window_days)

    try:
        resp = requests.get(source["widget_url"], headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as exc:
        log.warning("LibCal widget fetch failed for %s: %s", name, exc)
        return [], {"source": name, "status": "error", "error": str(exc), "count": 0}

    if "calevent-mini" not in resp.text:
        log.warning("LibCal widget for %s returned unexpected content", name)
        return [], {
            "source": name,
            "status": "error",
            "error": "unexpected content",
            "count": 0,
        }

    events = _parse_widget_html(resp.text, source, now, cutoff)

    health = {
        "source": name,
        "status": "ok",
        "count": len(events),
    }
    log.info("LibCal widget %s: %d kids events", name, len(events))
    return events, health


def scrape_all_libcal_widget(window_days: int = 16) -> tuple[list[dict], list[dict]]:
    """Scrape all LibCal widget sources. Returns (events, health_records)."""
    all_events: list[dict] = []
    all_health: list[dict] = []

    for i, source in enumerate(LIBCAL_WIDGET_SOURCES):
        if i > 0:
            # Respect robots.txt crawl-delay: 10 seconds
            time.sleep(10)
        events, health = _scrape_one(source, window_days)
        all_events.extend(events)
        all_health.append(health)

    return all_events, all_health
