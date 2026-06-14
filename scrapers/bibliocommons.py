"""
BiblioCommons library event scraper — uses the gateway JSON API.
Targets: Palo Alto, San Mateo County, San Jose Public, Santa Clara County,
San Francisco Public, Oakland, Berkeley, and Santa Cruz City libraries.
Coverage area: roughly within 40 miles of Palo Alto.
"""

import re
import hashlib
import logging
from datetime import datetime, timedelta, timezone
import requests

log = logging.getLogger(__name__)

LIBRARIES = [
    # Peninsula / South Bay (original coverage)
    {"name": "Palo Alto City Library",            "slug": "paloalto",  "county": "Santa Clara"},
    {"name": "San Mateo County Library",           "slug": "smcl",      "county": "San Mateo"},
    {"name": "San Jose Public Library",            "slug": "sjpl",      "county": "Santa Clara"},
    {"name": "Santa Clara County Library District","slug": "sccl",      "county": "Santa Clara"},
    # SF / East Bay (expanded — within 40 miles of Palo Alto)
    {"name": "San Francisco Public Library",       "slug": "sfpl",      "county": "San Francisco"},
    {"name": "Oakland Public Library",             "slug": "oaklandlibrary", "county": "Alameda"},
    {"name": "Berkeley Public Library",            "slug": "berkeleypubliclibrary", "county": "Alameda"},
    {"name": "Santa Cruz City Libraries",          "slug": "santacruz", "county": "Santa Cruz"},
]

GATEWAY = "https://gateway.bibliocommons.com/v2/libraries/{slug}/events"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

ADULT_NOISE = re.compile(
    r"\b(job\s*fair|resume|career|financial\s*planning|tax|voter|citizenship|"
    r"english\s*as\s*a\s*second|esl|gre\s*prep|sat\s*prep|21\+|adults?\s*only|"
    r"senior\s*center|medicare|aarp|city\s*council|planning\s*commission)\b",
    re.IGNORECASE,
)

MULTI_WEEK_CAMP = re.compile(
    r"\b(summer\s*camp|week[\-\s]?long\s*camp|multi[\-\s]?week)\b", re.IGNORECASE
)

# Audience IDs that signal kids/family events (varies per system; we also allow unknown)
# We filter by title keywords rather than ID to stay system-agnostic.
KID_KEYWORDS = re.compile(
    r"\b(child|children|kids?|family|families|toddler|baby|babies|infant|"
    r"storytime|story\s*time|preschool|pre-?k|tween|teen|youth|junior)\b",
    re.IGNORECASE,
)


def _dedupe_key(title: str, date_str: str, city: str) -> str:
    raw = f"{title.lower().strip()}|{date_str}|{city.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def scrape_library(lib: dict, window_days: int = 16) -> list[dict]:
    slug = lib["slug"]
    county = lib["county"]
    source_name = lib["name"]
    base_url = f"https://{slug}.bibliocommons.com"
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=window_days)

    events = []

    # Paginate — API returns 10/page by default; limit pages to keep runtime sane
    for page in range(1, 11):
        url = GATEWAY.format(slug=slug)
        params = {"locale": "en-US", "page": page, "limit": 50}
        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning("%s page %d failed: %s", source_name, page, exc)
            break

        item_ids = data.get("events", {}).get("items", [])
        if not item_ids:
            break

        entities = data.get("entities", {}).get("events", {})
        pagination = data.get("events", {}).get("pagination", {})

        for eid in item_ids:
            entity = entities.get(eid, {})
            defn = entity.get("definition", {})

            title = defn.get("title", "").strip()
            if not title:
                continue

            # Keep only kid/family events; skip adult noise
            if ADULT_NOISE.search(title):
                continue
            if not KID_KEYWORDS.search(title):
                # Also check description snippet
                desc = defn.get("description", "")
                if not KID_KEYWORDS.search(desc):
                    continue

            start_raw = defn.get("start", "")
            end_raw = defn.get("end", "")
            # BiblioCommons returns naive local times (America/Los_Angeles) — store as-is
            try:
                start_dt = datetime.fromisoformat(start_raw)
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)  # placeholder; display layer reads raw ISO
            except Exception:
                start_dt = None
            try:
                end_dt = datetime.fromisoformat(end_raw)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
            except Exception:
                end_dt = None

            if start_dt:
                if start_dt < now or start_dt > cutoff:
                    continue

            branch_id = defn.get("branchLocationId", "")
            location_detail = defn.get("locationDetails", "")
            venue = f"{source_name} — {location_detail}" if location_detail else source_name

            # Registration
            reg = defn.get("registration", {}) or {}
            requires_reg = reg.get("type") not in (None, "no_registration")
            ticket_status = "register ahead" if requires_reg else "free walk-up"
            reg_url = reg.get("externalUrl") or f"{base_url}/events/{eid}"

            date_str = start_dt.date().isoformat() if start_dt else start_raw[:10]
            is_camp = bool(MULTI_WEEK_CAMP.search(title))

            events.append({
                "title": title,
                "start_datetime": start_dt.isoformat() if start_dt else None,
                "end_datetime": end_dt.isoformat() if end_dt else None,
                "venue": venue,
                "city": source_name,
                "county": county,
                "age_range": "Families",
                "cost": "Free",
                "cost_amount": 0.0,
                "ticket_status": ticket_status,
                "ticket_url": reg_url,
                "category": "camp" if is_camp else "library",
                "source_channel": "library",
                "source_name": source_name,
                "source_url": f"{base_url}/v2/events",
                "last_verified": now.isoformat(),
                "dedupe_key": _dedupe_key(title, date_str, venue),
                "is_camp": is_camp,
            })

        # Stop if we've consumed all pages
        if page >= pagination.get("pages", 1):
            break

    log.info("%s: scraped %d events", source_name, len(events))
    return events


def scrape_all_libraries(window_days: int = 16) -> tuple[list[dict], list[dict]]:
    all_events = []
    health = []
    for lib in LIBRARIES:
        try:
            events = scrape_library(lib, window_days)
            all_events.extend(events)
            health.append({"source": lib["name"], "status": "ok", "count": len(events)})
        except Exception as exc:
            log.error("Library scraper failed for %s: %s", lib["name"], exc)
            health.append({"source": lib["name"], "status": "error", "error": str(exc), "count": 0})
    return all_events, health
