"""
Eventbrite scraper — extracts events from window.__SERVER_DATA__ embedded in search pages.
Uses /d/ca--{city}/family/ pages which reliably include a search_data.events.results list.
Coverage: Peninsula, South Bay, SF, East Bay, and Santa Cruz (within 40 miles of Palo Alto).
"""

import re
import json
import hashlib
import logging
from datetime import datetime, timedelta, timezone
import requests

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*",
}

CITIES = [
    # Peninsula / South Bay (original)
    ("palo-alto",     "Palo Alto",     "Santa Clara"),
    ("san-jose",      "San Jose",      "Santa Clara"),
    ("mountain-view", "Mountain View", "Santa Clara"),
    ("sunnyvale",     "Sunnyvale",     "Santa Clara"),
    ("san-mateo",     "San Mateo",     "San Mateo"),
    ("redwood-city",  "Redwood City",  "San Mateo"),
    ("menlo-park",    "Menlo Park",    "San Mateo"),
    # SF / East Bay / Santa Cruz (expanded — within 40 miles of Palo Alto)
    ("san-francisco", "San Francisco", "San Francisco"),
    ("oakland",       "Oakland",       "Alameda"),
    ("berkeley",      "Berkeley",      "Alameda"),
    ("santa-cruz",    "Santa Cruz",    "Santa Cruz"),
]

ADULT_NOISE = re.compile(
    r"\b(networking|job\s*fair|happy\s*hour|wine\s*tasting|comedy\s*show|21\+|"
    r"adults?\s*only|bachelorette|bar\s*crawl|nightclub|constellation\s*session)\b",
    re.IGNORECASE,
)

MULTI_WEEK_CAMP = re.compile(r"\b(summer\s*camp|week[\-\s]?long\s*camp|multi[\-\s]?week)\b", re.IGNORECASE)

# Map venue city → county so events that land far from the search city get the right county
CITY_COUNTY = {
    "san francisco": "San Francisco", "daly city": "San Mateo", "south san francisco": "San Mateo",
    "oakland": "Alameda", "berkeley": "Alameda", "alameda": "Alameda", "emeryville": "Alameda",
    "fremont": "Alameda", "hayward": "Alameda", "san leandro": "Alameda", "union city": "Alameda",
    "newark": "Alameda", "piedmont": "Alameda", "albany": "Alameda", "castro valley": "Alameda",
    "richmond": "Contra Costa", "el cerrito": "Contra Costa", "san pablo": "Contra Costa",
    "concord": "Contra Costa", "walnut creek": "Contra Costa", "pleasant hill": "Contra Costa",
    "martinez": "Contra Costa", "antioch": "Contra Costa", "pittsburg": "Contra Costa",
    "hercules": "Contra Costa", "pinole": "Contra Costa", "danville": "Contra Costa",
    "livermore": "Alameda", "pleasanton": "Alameda", "dublin": "Alameda",
    "palo alto": "Santa Clara", "mountain view": "Santa Clara", "sunnyvale": "Santa Clara",
    "cupertino": "Santa Clara", "santa clara": "Santa Clara", "san jose": "Santa Clara",
    "los altos": "Santa Clara", "campbell": "Santa Clara", "los gatos": "Santa Clara",
    "saratoga": "Santa Clara", "milpitas": "Santa Clara", "morgan hill": "Santa Clara",
    "menlo park": "San Mateo", "redwood city": "San Mateo", "san mateo": "San Mateo",
    "san carlos": "San Mateo", "belmont": "San Mateo", "foster city": "San Mateo",
    "burlingame": "San Mateo", "millbrae": "San Mateo", "san bruno": "San Mateo",
    "half moon bay": "San Mateo", "atherton": "San Mateo",
    "santa cruz": "Santa Cruz", "capitola": "Santa Cruz", "scotts valley": "Santa Cruz",
    "watsonville": "Santa Cruz", "aptos": "Santa Cruz",
    "sausalito": "Marin", "san rafael": "Marin", "novato": "Marin",
}

def _county_for_city(city: str, default: str) -> str:
    return CITY_COUNTY.get(city.lower().strip(), default)

SERVER_DATA_RE = re.compile(r'window\.__SERVER_DATA__\s*=\s*(\{.+)', re.DOTALL)


def _dedupe_key(title: str, date_str: str, city: str) -> str:
    raw = f"{title.lower().strip()}|{date_str}|{city.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _extract_server_data(html: str) -> dict:
    m = SERVER_DATA_RE.search(html)
    if not m:
        return {}
    raw = m.group(1)
    depth = end = 0
    for i, c in enumerate(raw):
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    try:
        return json.loads(raw[:end])
    except Exception:
        return {}


def scrape_city(city_slug: str, city_name: str, county: str, window_days: int = 16) -> list[dict]:
    url = f"https://www.eventbrite.com/d/ca--{city_slug}/family/"
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=window_days)
    events = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as exc:
        log.warning("Eventbrite fetch failed for %s: %s", city_name, exc)
        return []

    data = _extract_server_data(resp.text)
    if not data:
        log.warning("Eventbrite: no SERVER_DATA found for %s", city_name)
        return []

    results = data.get("search_data", {}).get("events", {}).get("results", [])

    for item in results:
        title = item.get("name", "").strip()
        if not title or ADULT_NOISE.search(title):
            continue

        start_date = item.get("start_date", "")
        start_time = item.get("start_time", "00:00")
        end_date = item.get("end_date", "")
        end_time = item.get("end_time", "")

        try:
            start_dt = datetime.fromisoformat(f"{start_date}T{start_time}").replace(tzinfo=timezone.utc)
        except Exception:
            start_dt = None

        if start_dt and (start_dt < now or start_dt > cutoff):
            continue

        try:
            end_dt = datetime.fromisoformat(f"{end_date}T{end_time}").replace(tzinfo=timezone.utc) if end_date and end_time else None
        except Exception:
            end_dt = None

        venue_info = item.get("primary_venue", {}) or {}
        venue_name = venue_info.get("name", city_name)
        venue_city = (venue_info.get("address", {}) or {}).get("city", city_name)
        # Use actual venue city to determine county — Eventbrite search results can span far
        actual_county = _county_for_city(venue_city, county)

        ticket_url = item.get("url", url)
        is_free = item.get("is_free", False)
        cost_label = "Free" if is_free else "Paid"
        cost_amt = 0.0 if is_free else 1.0  # unknown amount; flag as paid

        is_cancelled = item.get("is_cancelled", False)
        if is_cancelled:
            continue

        is_camp = bool(MULTI_WEEK_CAMP.search(title))
        date_str = start_date

        events.append({
            "title": title,
            "start_datetime": start_dt.isoformat() if start_dt else None,
            "end_datetime": end_dt.isoformat() if end_dt else None,
            "venue": venue_name,
            "city": venue_city,
            "county": actual_county,
            "age_range": "Families",
            "cost": cost_label,
            "cost_amount": cost_amt,
            "ticket_status": "free walk-up" if is_free else "book ahead",
            "ticket_url": ticket_url,
            "category": "camp" if is_camp else "eventbrite",
            "source_channel": "eventbrite",
            "source_name": f"Eventbrite / {city_name}",
            "source_url": url,
            "last_verified": now.isoformat(),
            "dedupe_key": _dedupe_key(title, date_str, venue_city),
            "is_camp": is_camp,
        })

    log.info("Eventbrite %s: scraped %d events", city_name, len(events))
    return events


def scrape_all_eventbrite(window_days: int = 16) -> tuple[list[dict], list[dict]]:
    all_events = []
    health = []
    for city_slug, city_name, county in CITIES:
        try:
            events = scrape_city(city_slug, city_name, county, window_days)
            all_events.extend(events)
            health.append({"source": f"Eventbrite/{city_name}", "status": "ok", "count": len(events)})
        except Exception as exc:
            log.error("Eventbrite scraper failed for %s: %s", city_name, exc)
            health.append({"source": f"Eventbrite/{city_name}", "status": "error", "error": str(exc), "count": 0})
    return all_events, health
