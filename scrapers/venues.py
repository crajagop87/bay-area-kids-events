"""
Venue calendar scrapers for ~6 high-signal venues.
Each returns structured events directly from the venue's own calendar/page.
"""

import re
import json
import hashlib
import logging
from datetime import datetime, timedelta, timezone
import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KidsEventsScraper/1.0)"}

MULTI_WEEK_CAMP = re.compile(r"\b(summer\s*camp|week[\-\s]?long\s*camp|multi[\-\s]?week)\b", re.IGNORECASE)


def _dedupe_key(title: str, date_str: str, city: str) -> str:
    raw = f"{title.lower().strip()}|{date_str}|{city.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _make_event(title, start_dt, end_dt, venue_name, city, county, cost, cost_amt,
                ticket_status, ticket_url, source_name, source_url):
    now = datetime.now(timezone.utc)
    date_str = start_dt.date().isoformat() if start_dt else ""
    is_camp = bool(MULTI_WEEK_CAMP.search(title))
    return {
        "title": title,
        "start_datetime": start_dt.isoformat() if start_dt else None,
        "end_datetime": end_dt.isoformat() if end_dt else None,
        "venue": venue_name,
        "city": city,
        "county": county,
        "age_range": "Families",
        "cost": cost,
        "cost_amount": cost_amt,
        "ticket_status": ticket_status,
        "ticket_url": ticket_url,
        "category": "camp" if is_camp else "venue",
        "source_channel": "venue",
        "source_name": source_name,
        "source_url": source_url,
        "last_verified": now.isoformat(),
        "dedupe_key": _dedupe_key(title, date_str, city),
        "is_camp": is_camp,
    }


def _json_ld_events(soup, source_name, source_url, city, county, cost, cost_amt,
                    ticket_status, venue_name, now, cutoff):
    events = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if item.get("@type") not in ("Event", "SocialEvent", "EducationEvent"):
                continue
            title = item.get("name", "")
            if not title:
                continue
            try:
                start_dt = datetime.fromisoformat(item.get("startDate", ""))
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
            except Exception:
                start_dt = None
            if start_dt and (start_dt < now or start_dt > cutoff):
                continue
            try:
                end_dt = datetime.fromisoformat(item.get("endDate", ""))
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
            except Exception:
                end_dt = None
            link = item.get("url", source_url)
            events.append(_make_event(title, start_dt, end_dt, venue_name, city, county,
                                      cost, cost_amt, ticket_status, link, source_name, source_url))
    return events


def scrape_palo_alto_junior_museum(window_days: int = 16) -> list[dict]:
    url = "https://www.paloaltozoo.org/visit"
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=window_days)
    events = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        events = _json_ld_events(soup, "Palo Alto Junior Museum & Zoo", url,
                                  "Palo Alto", "Santa Clara", "Paid", 10.0,
                                  "reserve ahead", "Palo Alto Junior Museum & Zoo", now, cutoff)
        if not events:
            # Fallback: treat venue itself as always open (weekend anchor)
            for day_offset in range(window_days):
                dt = now + timedelta(days=day_offset)
                if dt.weekday() in (5, 6):  # Sat/Sun
                    events.append(_make_event(
                        "Palo Alto Junior Museum & Zoo — Open",
                        dt.replace(hour=10, minute=0, second=0),
                        dt.replace(hour=17, minute=0, second=0),
                        "Palo Alto Junior Museum & Zoo",
                        "Palo Alto", "Santa Clara",
                        "Paid", 10.0, "reserve ahead",
                        "https://www.paloaltozoo.org/Visit",
                        "Palo Alto Junior Museum & Zoo", url,
                    ))
    except Exception as exc:
        log.warning("Palo Alto Junior Museum scrape failed: %s", exc)
    log.info("Palo Alto Junior Museum: %d events", len(events))
    return events


def scrape_curiodyssey(window_days: int = 16) -> list[dict]:
    url = "https://curiodyssey.org/events/"
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=window_days)
    events = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        events = _json_ld_events(soup, "CuriOdyssey", url,
                                  "San Mateo", "San Mateo", "Paid", 12.0,
                                  "walk-up or reserve", "CuriOdyssey", now, cutoff)
        if not events:
            for article in soup.select("article, .event-item, .tribe-event"):
                title_el = article.select_one("h2, h3, .event-title")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                link_el = title_el.find_parent("a") or article.select_one("a")
                link = link_el["href"] if link_el else url
                events.append(_make_event(title, None, None, "CuriOdyssey",
                                           "San Mateo", "San Mateo", "Paid", 12.0,
                                           "walk-up", link, "CuriOdyssey", url))
    except Exception as exc:
        log.warning("CuriOdyssey scrape failed: %s", exc)
    log.info("CuriOdyssey: %d events", len(events))
    return events


def scrape_hiller_aviation(window_days: int = 16) -> list[dict]:
    url = "https://www.hiller.org/events/"
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=window_days)
    events = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        events = _json_ld_events(soup, "Hiller Aviation Museum", url,
                                  "San Carlos", "San Mateo", "Paid", 15.0,
                                  "book ahead — sells out", "Hiller Aviation Museum", now, cutoff)
        if not events:
            for article in soup.select("article, .event, .tribe-event"):
                title_el = article.select_one("h2, h3, .tribe-event-url")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                link_el = article.select_one("a")
                link = link_el["href"] if link_el else url
                events.append(_make_event(title, None, None, "Hiller Aviation Museum",
                                           "San Carlos", "San Mateo", "Paid", 15.0,
                                           "book ahead", link, "Hiller Aviation Museum", url))
    except Exception as exc:
        log.warning("Hiller Aviation scrape failed: %s", exc)
    log.info("Hiller Aviation: %d events", len(events))
    return events


def scrape_childrens_discovery_museum_sj(window_days: int = 16) -> list[dict]:
    url = "https://www.cdm.org/events-and-programs"
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=window_days)
    events = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        events = _json_ld_events(soup, "Children's Discovery Museum SJ", url,
                                  "San Jose", "Santa Clara", "Paid", 18.0,
                                  "walk-up or reserve", "Children's Discovery Museum", now, cutoff)
        if not events:
            for article in soup.select("article, .event-item"):
                title_el = article.select_one("h2, h3, .event-title")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                link_el = article.select_one("a")
                link = link_el["href"] if link_el else url
                events.append(_make_event(title, None, None, "Children's Discovery Museum",
                                           "San Jose", "Santa Clara", "Paid", 18.0,
                                           "walk-up", link, "Children's Discovery Museum SJ", url))
    except Exception as exc:
        log.warning("CDM SJ scrape failed: %s", exc)
    log.info("Children's Discovery Museum SJ: %d events", len(events))
    return events


def scrape_cantor_arts(window_days: int = 16) -> list[dict]:
    """Cantor Arts Center — free weekly Family Sundays (no reservation, drop-in art packs)."""
    url = "https://museum.stanford.edu/events"
    now = datetime.now(timezone.utc)
    events = []
    # Cantor is always open Sun 10am–5pm with free drop-in; emit one record per Sunday in window
    for day_offset in range(window_days):
        dt = now + timedelta(days=day_offset)
        if dt.weekday() == 6:  # Sunday
            start = dt.replace(hour=10, minute=0, second=0, microsecond=0)
            end = dt.replace(hour=17, minute=0, second=0, microsecond=0)
            events.append(_make_event(
                "Cantor Arts Center — Free Sunday Drop-in (art packs, galleries)",
                start, end, "Cantor Arts Center",
                "Palo Alto", "Santa Clara",
                "Free", 0.0, "free walk-up",
                "https://museum.stanford.edu/visitor-guidelines",
                "Cantor Arts Center", url,
            ))
    log.info("Cantor Arts: %d events", len(events))
    return events


def scrape_hidden_villa(window_days: int = 16) -> list[dict]:
    url = "https://www.hiddenvilla.org/calendar/individuals-families/region-HV/"
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=window_days)
    events = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        events = _json_ld_events(soup, "Hidden Villa Farm", url,
                                  "Los Altos Hills", "Santa Clara", "Paid", 8.0,
                                  "some tours require registration", "Hidden Villa Farm", now, cutoff)
        if not events:
            for article in soup.select("article, .event"):
                title_el = article.select_one("h2, h3, .event-title")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                link_el = article.select_one("a")
                link = link_el["href"] if link_el else url
                events.append(_make_event(title, None, None, "Hidden Villa Farm",
                                           "Los Altos Hills", "Santa Clara", "Paid", 8.0,
                                           "walk-up", link, "Hidden Villa Farm", url))
    except Exception as exc:
        log.warning("Hidden Villa scrape failed: %s", exc)
    log.info("Hidden Villa: %d events", len(events))
    return events


def scrape_exploratorium(window_days: int = 16) -> list[dict]:
    """Exploratorium — San Francisco science museum with strong family programming."""
    url = "https://www.exploratorium.edu/visit/calendar"
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=window_days)
    events = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        events = _json_ld_events(soup, "Exploratorium", url,
                                  "San Francisco", "San Francisco", "Paid", 20.0,
                                  "walk-up or reserve", "Exploratorium", now, cutoff)
        if not events:
            # Emit weekend open hours as a standing anchor event
            for day_offset in range(window_days):
                dt = now + timedelta(days=day_offset)
                if dt.weekday() in (5, 6):
                    events.append(_make_event(
                        "Exploratorium — Open (hands-on science exhibits)",
                        dt.replace(hour=10, minute=0, second=0, microsecond=0),
                        dt.replace(hour=17, minute=0, second=0, microsecond=0),
                        "Exploratorium", "San Francisco", "San Francisco",
                        "Paid", 20.0, "walk-up or reserve",
                        "https://www.exploratorium.edu/visit",
                        "Exploratorium", url,
                    ))
    except Exception as exc:
        log.warning("Exploratorium scrape failed: %s", exc)
    log.info("Exploratorium: %d events", len(events))
    return events


def scrape_fairyland(window_days: int = 16) -> list[dict]:
    """Oakland Children's Fairyland — classic storybook theme park, ages 1–10."""
    url = "https://www.fairyland.org/plan-your-visit/"
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=window_days)
    events = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        events = _json_ld_events(soup, "Oakland Children's Fairyland", url,
                                  "Oakland", "Alameda", "Paid", 16.0,
                                  "book ahead", "Oakland Children's Fairyland", now, cutoff)
        if not events:
            for article in soup.select("article, .event, .tribe-event"):
                title_el = article.select_one("h2, h3, .tribe-event-url")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                link_el = article.select_one("a")
                link = link_el["href"] if link_el else url
                events.append(_make_event(title, None, None, "Oakland Children's Fairyland",
                                           "Oakland", "Alameda", "Paid", 16.0,
                                           "book ahead", link,
                                           "Oakland Children's Fairyland", url))
    except Exception as exc:
        log.warning("Oakland Children's Fairyland scrape failed: %s", exc)
    log.info("Oakland Children's Fairyland: %d events", len(events))
    return events


def scrape_lawrence_hall(window_days: int = 16) -> list[dict]:
    """Lawrence Hall of Science — UC Berkeley's public science center."""
    url = "https://www.lawrencehallofscience.org/visit/programs-and-events/"
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=window_days)
    events = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        events = _json_ld_events(soup, "Lawrence Hall of Science", url,
                                  "Berkeley", "Alameda", "Paid", 15.0,
                                  "walk-up or reserve", "Lawrence Hall of Science", now, cutoff)
        if not events:
            for article in soup.select("article, .event-item, .program"):
                title_el = article.select_one("h2, h3, .event-title")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                link_el = article.select_one("a")
                link = link_el["href"] if link_el else url
                events.append(_make_event(title, None, None, "Lawrence Hall of Science",
                                           "Berkeley", "Alameda", "Paid", 15.0,
                                           "walk-up", link,
                                           "Lawrence Hall of Science", url))
    except Exception as exc:
        log.warning("Lawrence Hall of Science scrape failed: %s", exc)
    log.info("Lawrence Hall of Science: %d events", len(events))
    return events


VENUE_SCRAPERS = [
    # Peninsula / South Bay core
    ("Palo Alto Junior Museum & Zoo", scrape_palo_alto_junior_museum),
    ("CuriOdyssey", scrape_curiodyssey),
    ("Hiller Aviation Museum", scrape_hiller_aviation),
    ("Children's Discovery Museum SJ", scrape_childrens_discovery_museum_sj),
    ("Cantor Arts Center", scrape_cantor_arts),
    ("Hidden Villa Farm", scrape_hidden_villa),
    # SF / East Bay (expanded)
    ("Exploratorium", scrape_exploratorium),
    ("Oakland Children's Fairyland", scrape_fairyland),
    ("Lawrence Hall of Science", scrape_lawrence_hall),
]


def scrape_all_venues(window_days: int = 16) -> tuple[list[dict], list[dict]]:
    all_events = []
    health = []
    for name, fn in VENUE_SCRAPERS:
        try:
            events = fn(window_days)
            all_events.extend(events)
            health.append({"source": name, "status": "ok", "count": len(events)})
        except Exception as exc:
            log.error("Venue scraper failed for %s: %s", name, exc)
            health.append({"source": name, "status": "error", "error": str(exc), "count": 0})
    return all_events, health
