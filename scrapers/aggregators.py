"""
Curated aggregator scrapers: Funcheap, Bay Area Kid Fun, Mommy Poppins.
Supplementary to library + Eventbrite; catches festivals/fairs.
"""

import re
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import requests
from bs4 import BeautifulSoup
from scrapers.tagger import ADULT_NOISE

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KidsEventsScraper/1.0)"}

MULTI_WEEK_CAMP = re.compile(r"\b(summer\s*camp|week[\-\s]?long\s*camp|multi[\-\s]?week)\b", re.IGNORECASE)


def _dedupe_key(title: str, date_str: str, city: str) -> str:
    raw = f"{title.lower().strip()}|{date_str}|{city.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _parse_cost(text: str) -> tuple[str, float]:
    if not text:
        return "Unknown", 0.0
    if re.search(r"\bfree\b", text, re.IGNORECASE):
        return "Free", 0.0
    m = re.search(r"\$\s*([\d,.]+)", text)
    if m:
        return "Paid", float(m.group(1).replace(",", ""))
    return "Paid", 0.0


def _parse_date_fuzzy(text: str) -> Optional[datetime]:
    for fmt in ("%B %d, %Y %I:%M %p", "%B %d, %Y", "%b %d, %Y", "%b. %d, %Y",
                "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _base_event(title, start_dt, end_dt, venue, city, county, cost_label, cost_amt,
                ticket_url, source_name, source_url):
    now = datetime.now(timezone.utc)
    date_str = start_dt.date().isoformat() if start_dt else ""
    is_camp = bool(MULTI_WEEK_CAMP.search(title))
    return {
        "title": title,
        "start_datetime": start_dt.isoformat() if start_dt else None,
        "end_datetime": end_dt.isoformat() if end_dt else None,
        "venue": venue,
        "city": city,
        "county": county,
        "age_range": "Families",
        "cost": cost_label,
        "cost_amount": cost_amt,
        "ticket_status": "book ahead" if cost_amt > 0 else "free walk-up",
        "ticket_url": ticket_url,
        "category": "camp" if is_camp else "aggregator",
        "source_channel": "aggregator",
        "source_name": source_name,
        "source_url": source_url,
        "last_verified": now.isoformat(),
        "dedupe_key": _dedupe_key(title, date_str, city),
        "is_camp": is_camp,
    }


# ---------------------------------------------------------------------------
# Funcheap
# ---------------------------------------------------------------------------

def scrape_funcheap(window_days: int = 16) -> list[dict]:
    url = "https://sf.funcheap.com/category/event/event-types/kids-families/"
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=window_days)
    events = []

    for page in range(1, 4):
        page_url = url if page == 1 else f"{url}page/{page}/"
        try:
            resp = requests.get(page_url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            log.warning("Funcheap page %d failed: %s", page, exc)
            break

        soup = BeautifulSoup(resp.text, "html.parser")

        # Funcheap uses WordPress-style article listings
        for article in soup.select("article, div.post, div.event"):
            title_el = article.select_one("h2 a, h3 a, .entry-title a")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if ADULT_NOISE.search(title):
                continue

            link = title_el.get("href", url)

            date_el = article.select_one("time, .event-date, .date, [class*='date']")
            date_raw = (date_el.get("datetime") or date_el.get_text(strip=True)) if date_el else ""
            start_dt = _parse_date_fuzzy(date_raw) if date_raw else None

            if start_dt and (start_dt < now or start_dt > cutoff):
                continue

            cost_el = article.select_one(".event-cost, [class*='cost'], [class*='price']")
            cost_text = cost_el.get_text(strip=True) if cost_el else ""
            cost_label, cost_amt = _parse_cost(cost_text)

            loc_el = article.select_one(".event-location, [class*='location']")
            location = loc_el.get_text(strip=True) if loc_el else "Bay Area"

            events.append(_base_event(
                title=title,
                start_dt=start_dt,
                end_dt=None,
                venue=location,
                city=location,
                county="Bay Area",
                cost_label=cost_label,
                cost_amt=cost_amt,
                ticket_url=link,
                source_name="Funcheap",
                source_url=page_url,
            ))

        if not soup.select_one("a.next, .pagination-next a, [rel='next']"):
            break

    log.info("Funcheap: scraped %d events", len(events))
    return events


# ---------------------------------------------------------------------------
# Bay Area Kid Fun
# ---------------------------------------------------------------------------

def scrape_bayareakidfun(window_days: int = 16) -> list[dict]:
    url = "https://www.bayareakidfun.com/weekend-highlights/"
    now = datetime.now(timezone.utc)
    events = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as exc:
        log.warning("Bay Area Kid Fun fetch failed: %s", exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract JSON-LD events
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if item.get("@type") not in ("Event", "SocialEvent"):
                continue
            title = item.get("name", "")
            if not title or ADULT_NOISE.search(title):
                continue
            try:
                start_dt = datetime.fromisoformat(item.get("startDate", ""))
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
            except Exception:
                start_dt = None

            location = item.get("location", {})
            venue = location.get("name", "Bay Area") if isinstance(location, dict) else "Bay Area"
            link = item.get("url", url)
            cost_label, cost_amt = "Unknown", 0.0

            events.append(_base_event(
                title=title,
                start_dt=start_dt,
                end_dt=None,
                venue=venue,
                city=venue,
                county="Bay Area",
                cost_label=cost_label,
                cost_amt=cost_amt,
                ticket_url=link,
                source_name="Bay Area Kid Fun",
                source_url=url,
            ))

    # Fallback: parse article links if no JSON-LD
    if not events:
        for a in soup.select("article a, .entry-content a"):
            title = a.get_text(strip=True)
            if len(title) < 10 or ADULT_NOISE.search(title):
                continue
            link = a.get("href", url)
            events.append(_base_event(
                title=title,
                start_dt=None,
                end_dt=None,
                venue="Bay Area",
                city="Bay Area",
                county="Bay Area",
                cost_label="Unknown",
                cost_amt=0.0,
                ticket_url=link,
                source_name="Bay Area Kid Fun",
                source_url=url,
            ))

    log.info("Bay Area Kid Fun: scraped %d events", len(events))
    return events


# ---------------------------------------------------------------------------
# 510 Families (replaces Mommy Poppins Bay Area, which has no working URL)
# Parses their RSS feed to find weekend roundup posts, then extracts event
# titles + links from the post body.
# ---------------------------------------------------------------------------

def scrape_510families(window_days: int = 16) -> list[dict]:
    rss_url = "https://www.510families.com/feed/"
    now = datetime.now(timezone.utc)
    events = []

    try:
        resp = requests.get(rss_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "xml")
    except Exception as exc:
        log.warning("510 Families RSS fetch failed: %s", exc)
        return []

    URL_NOISE = re.compile(
        r"facebook\.com|twitter\.com|instagram\.com|tinyurl\.com|"
        r"510families\.com/best|510families\.com/bay|510families\.com$",
        re.IGNORECASE,
    )
    STALE_YEAR = re.compile(r"/20(2[0-3])/|[/-]20(2[0-3])-")  # 2020-2023 in URL path
    WEEKEND_RE = re.compile(r"weekend|things\s+to\s+do|fun\s+things", re.IGNORECASE)
    cutoff_old = now - timedelta(days=60)  # ignore RSS posts older than 60 days

    for item in soup.find_all("item"):
        title_el = item.find("title")
        if not title_el or not WEEKEND_RE.search(title_el.get_text()):
            continue

        # Skip posts published more than 60 days ago
        pub_el = item.find("pubDate")
        if pub_el:
            try:
                from email.utils import parsedate_to_datetime
                pub_dt = parsedate_to_datetime(pub_el.get_text(strip=True))
                if pub_dt.replace(tzinfo=timezone.utc) < cutoff_old:
                    continue
            except Exception:
                pass

        post_url = (item.find("link") or item.find("guid"))
        post_url = post_url.get_text(strip=True) if post_url else rss_url

        # Parse event links from the post body (HTML in <content:encoded>)
        content_el = item.find("content:encoded") or item.find("description")
        if not content_el:
            continue

        content_soup = BeautifulSoup(content_el.get_text(), "html.parser")
        for a in content_soup.find_all("a", href=True):
            event_title = a.get_text(strip=True)
            if len(event_title) < 8 or ADULT_NOISE.search(event_title):
                continue
            href = a["href"]
            if URL_NOISE.search(href) or STALE_YEAR.search(href):
                continue

            events.append(_base_event(
                title=event_title,
                start_dt=None,
                end_dt=None,
                venue="East Bay",
                city="East Bay",
                county="Alameda/Contra Costa",
                cost_label="Unknown",
                cost_amt=0.0,
                ticket_url=href,
                source_name="510 Families",
                source_url=post_url,
            ))

    log.info("510 Families: scraped %d events", len(events))
    return events


def scrape_all_aggregators(window_days: int = 16) -> tuple[list[dict], list[dict]]:
    all_events = []
    health = []
    for name, fn in [("Funcheap", scrape_funcheap),
                     ("Bay Area Kid Fun", scrape_bayareakidfun),
                     ("510 Families", scrape_510families)]:
        try:
            events = fn(window_days)
            all_events.extend(events)
            health.append({"source": name, "status": "ok", "count": len(events)})
        except Exception as exc:
            log.error("%s scraper error: %s", name, exc)
            health.append({"source": name, "status": "error", "error": str(exc), "count": 0})
    return all_events, health
