"""
Venue calendar scrapers for ~6 high-signal venues.
Each returns structured events directly from the venue's own calendar/page.
"""

import re
import json
import hashlib
import html as html_mod
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup

PACIFIC = ZoneInfo("America/Los_Angeles")

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
            title = html_mod.unescape(item.get("name", ""))
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


def scrape_libcal_ics(domain: str, cid: int, city: str, county: str,
                      source_name: str, window_days: int = 45) -> list[dict]:
    """Generic LibCal ICS scraper — works for any library using LibCal with a public calendar."""
    import email.utils
    KID_RE = re.compile(
        r"\b(child|children|kids?|family|families|toddler|baby|babies|infant|"
        r"storytime|story\s*time|preschool|pre-?k|tween|teen|youth|junior)\b",
        re.IGNORECASE,
    )
    url = f"https://{domain}/ical_subscribe.php?cid={cid}&cat=0&format=ics"
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=window_days)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        text = resp.text
    except Exception as exc:
        log.warning("%s ICS fetch failed: %s", source_name, exc)
        return []

    if not text.strip().startswith("BEGIN:VCALENDAR"):
        log.warning("%s: unexpected ICS response: %s", source_name, text[:60])
        return []

    def unfold(s):
        return re.sub(r"\r?\n[ \t]", "", s)

    def unescape(s):
        return s.replace("\\,", ",").replace("\\;", ";").replace("\\n", "\n").replace("\\\\", "\\")

    def parse_dt(s):
        s = s.strip()
        try:
            if s.endswith("Z"):
                # UTC — convert to Pacific so fmt_time (which reads raw hours) shows local time
                dt_utc = datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                dt_pt = dt_utc.astimezone(PACIFIC)
                return dt_pt.replace(tzinfo=timezone.utc)
            elif "T" in s:
                dt = datetime.strptime(s[:15], "%Y%m%dT%H%M%S")
                # LibCal naive local times — treat as Pacific
                return dt.replace(tzinfo=timezone.utc)
            else:
                return datetime.strptime(s[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
        except Exception:
            return None

    events = []
    for raw_block in unfold(text).split("BEGIN:VEVENT")[1:]:
        def field(name):
            m = re.search(rf"^{name}[^:]*:(.*)$", raw_block, re.MULTILINE)
            return unescape(m.group(1).strip()) if m else ""

        summary = field("SUMMARY")
        categories = field("CATEGORIES")
        description = field("DESCRIPTION")
        url_field = field("URL")
        location = field("LOCATION")

        haystack = f"{summary} {categories} {description}"
        if not KID_RE.search(haystack):
            continue

        start = parse_dt(field("DTSTART"))
        end_raw = field("DTEND")
        end = parse_dt(end_raw) if end_raw else None

        if not start or start < now or start > cutoff:
            continue

        cost = "free" if re.search(r"\bfree\b", haystack, re.I) else "unknown"
        events.append(_make_event(
            title=summary,
            start_dt=start,
            end_dt=end,
            venue_name=source_name,
            city=city,
            county=county,
            cost=cost,
            cost_amt=0 if cost == "free" else None,
            ticket_status="available",
            ticket_url=url_field or f"https://{domain}/calendar/events",
            source_name=source_name,
            source_url=f"https://{domain}/calendar/events",
        ))

    log.info("%s: %d kid events from ICS", source_name, len(events))
    return events



def scrape_midpeninsula_openspace(window_days: int = 45) -> list[dict]:
    """Midpeninsula Regional Open Space District — youth & families programs."""
    base_url = "https://www.openspace.org/events"
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=window_days)
    events = []
    seen = set()

    for page in range(1, 8):
        url = f"{base_url}?type=youth-families&page={page}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            log.warning("OpenSpace fetch failed page %d: %s", page, exc)
            break

        soup = BeautifulSoup(resp.text, "lxml")
        rows = soup.select("table tbody tr")
        if not rows:
            break

        for row in rows:
            tds = row.find_all("td")
            if len(tds) < 3:
                continue
            # Columns: Category | Title | Date | [Preserve] | [Miles]
            link_el = row.select_one("a[href*='/events/']")
            if not link_el:
                continue
            title = link_el.get_text(strip=True)
            if not title or title in seen:
                continue
            ticket_url = "https://www.openspace.org" + link_el["href"] if link_el["href"].startswith("/") else link_el["href"]

            # Date is in the td after the title td
            date_text = ""
            for td in tds:
                if link_el in td.descendants:
                    siblings = td.find_next_siblings("td")
                    if siblings:
                        date_text = siblings[0].get_text(strip=True)
                    break

            start_dt = None
            if date_text:
                # e.g. "Monday, Jun 29, 20269:00 am" — date+time concatenated, abbrev month
                m = re.search(r"[A-Za-z]+,\s*([A-Za-z]+\s+\d+,\s*\d{4})(\d+:\d+\s*[ap]m)?", date_text, re.IGNORECASE)
                if m:
                    ds = m.group(1).strip()
                    ts = m.group(2).strip() if m.group(2) else "9:00 AM"
                    try:
                        naive = datetime.strptime(f"{ds} {ts.upper()}", "%b %d, %Y %I:%M %p")
                        start_dt = naive.replace(tzinfo=timezone(timedelta(hours=-7)))
                    except Exception:
                        pass

            if start_dt and (start_dt < now or start_dt > cutoff):
                continue

            seen.add(title)
            events.append(_make_event(
                title, start_dt, None,
                "Midpeninsula Open Space", "Los Altos Hills", "Santa Clara",
                "Free", 0.0, "free walk-up", ticket_url,
                "Midpeninsula Open Space", base_url,
            ))

        if len(rows) < 10:
            break

    log.info("OpenSpace: scraped %d events", len(events))
    return events


_STANFORD_KID_RE = re.compile(
    r"\b(family|families|child|children|kids?|youth|teen|toddler|baby|babies|"
    r"preschool|elementary|storytime|science\s*fair|junior|puppet|magic\s*show|"
    r"summer\s*camp|art\s*camp|maker|lego|robot|coding\s*for\s*kids)\b",
    re.IGNORECASE,
)

def scrape_stanford_events(window_days: int = 45) -> list[dict]:
    """Stanford public events — filtered to family/kids-relevant content."""
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=window_days)
    events = []
    seen = set()

    for page in range(1, 6):
        try:
            resp = requests.get(
                "https://events.stanford.edu/api/2/events/",
                params={"audience": "Everyone", "page_size": 100, "page": page},
                headers=HEADERS, timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning("Stanford Events API failed page %d: %s", page, exc)
            break

        items = data.get("events", [])
        if not items:
            break

        for wrapper in items:
            ev = wrapper.get("event", wrapper)
            title = ev.get("title", "").strip()
            if not title:
                continue

            desc = ev.get("description_text", "") or ""
            haystack = f"{title} {desc}"
            if not _STANFORD_KID_RE.search(haystack):
                continue

            # Date from first event_instance
            instances = ev.get("event_instances", [])
            start_dt = end_dt = None
            if instances:
                inst = instances[0].get("event_instance", instances[0])
                try:
                    start_dt = datetime.fromisoformat(inst["start"])
                except Exception:
                    pass
                try:
                    end_dt = datetime.fromisoformat(inst["end"]) if inst.get("end") else None
                except Exception:
                    pass

            if start_dt and (start_dt < now or start_dt > cutoff):
                continue

            key = f"{title}|{ev.get('first_date','')}"
            if key in seen:
                continue
            seen.add(key)

            ticket_url = ev.get("localist_url") or ev.get("url") or "https://events.stanford.edu"
            is_free = ev.get("free", False)
            location = ev.get("location_name", "") or "Stanford University"

            events.append(_make_event(
                title, start_dt, end_dt,
                location, "Stanford", "Santa Clara",
                "Free" if is_free else "Paid",
                0.0 if is_free else 1.0,
                "free walk-up" if is_free else "check website",
                ticket_url, "Stanford Events", "https://events.stanford.edu",
            ))

        if len(items) < 100:
            break

    log.info("Stanford Events: scraped %d family-relevant events", len(events))
    return events


def scrape_allied_arts_guild(window_days: int = 45) -> list[dict]:
    """Allied Arts Guild (Menlo Park) — seasonal family events."""
    url = "https://alliedartsguild.org/events/"
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=window_days)
    events = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as exc:
        log.warning("Allied Arts Guild fetch failed: %s", exc)
        return []

    soup = BeautifulSoup(resp.text, "lxml")

    DATE_RE = re.compile(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{1,2}(?:–\d{1,2})?,?\s+\d{4}",
        re.IGNORECASE,
    )

    for article in soup.select("article, .entry-content > *"):
        title_el = article.select_one("h1, h2, h3, h4")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if not title or len(title) < 4:
            continue

        body = article.get_text(" ", strip=True)
        m = DATE_RE.search(body)
        start_dt = None
        if m:
            try:
                start_dt = datetime.strptime(m.group(0).replace("–", " ").split()[0] + " " + " ".join(m.group(0).split()[-2:]), "%B %d %Y").replace(tzinfo=timezone.utc)
            except Exception:
                pass

        if start_dt and (start_dt < now or start_dt > cutoff):
            continue

        link_el = article.select_one("a[href]")
        ticket_url = link_el["href"] if link_el else url

        events.append(_make_event(
            title, start_dt, None,
            "Allied Arts Guild", "Menlo Park", "San Mateo",
            "check website", 0.0, "check website", ticket_url,
            "Allied Arts Guild", url,
        ))

    log.info("Allied Arts Guild: scraped %d events", len(events))
    return events


VENUE_SCRAPERS = [
    # Peninsula / South Bay core
    ("Palo Alto Junior Museum & Zoo", scrape_palo_alto_junior_museum),
    ("CuriOdyssey", scrape_curiodyssey),
    ("Hiller Aviation Museum", scrape_hiller_aviation),
    ("Children's Discovery Museum SJ", scrape_childrens_discovery_museum_sj),
    ("Cantor Arts Center", scrape_cantor_arts),
    ("Hidden Villa Farm", scrape_hidden_villa),
    # Peninsula / open space
    ("Midpeninsula Open Space", scrape_midpeninsula_openspace),
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
