#!/usr/bin/env python3
"""
Bay Area Kids Events Scraper — main entry point.
Runs all channels, dedupes, writes output/events.json + output/health.json.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from scrapers.bibliocommons import scrape_all_libraries
from scrapers.eventbrite import scrape_all_eventbrite
from scrapers.aggregators import scrape_all_aggregators
from scrapers.venues import scrape_all_venues
from scrapers.tagger import tag_event, enrich_title

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("run_scraper")

OUTPUT_DIR = Path(__file__).parent / "output"
EVENTS_FILE = OUTPUT_DIR / "events.json"
HEALTH_FILE = OUTPUT_DIR / "health.json"

# Dedup priority: venue > library > eventbrite > aggregator
CHANNEL_PRIORITY = {"venue": 0, "library": 1, "eventbrite": 2, "aggregator": 3}


def dedupe(events: list[dict]) -> list[dict]:
    """Keep highest-priority source per dedupe_key."""
    seen: dict[str, dict] = {}
    for event in events:
        key = event.get("dedupe_key", "")
        if not key:
            continue
        if key not in seen:
            seen[key] = event
        else:
            existing_prio = CHANNEL_PRIORITY.get(seen[key]["source_channel"], 99)
            new_prio = CHANNEL_PRIORITY.get(event["source_channel"], 99)
            if new_prio < existing_prio:
                seen[key] = event
    return list(seen.values())


def sort_events(events: list[dict]) -> list[dict]:
    def sort_key(e):
        dt = e.get("start_datetime") or "9999"
        return dt
    return sorted(events, key=sort_key)


def main(window_days: int = 16):
    OUTPUT_DIR.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    all_events: list[dict] = []
    all_health: list[dict] = []

    log.info("=== Scrape run started: %s ===", now.isoformat())

    channels = [
        ("Libraries (BiblioCommons)", scrape_all_libraries),
        ("Eventbrite", scrape_all_eventbrite),
        ("Aggregators", scrape_all_aggregators),
        ("Venues", scrape_all_venues),
    ]

    for channel_name, fn in channels:
        log.info("--- Scraping: %s ---", channel_name)
        try:
            events, health = fn(window_days)
            all_events.extend(events)
            all_health.extend(health)
        except Exception as exc:
            log.error("Channel %s crashed: %s", channel_name, exc)
            all_health.append({"source": channel_name, "status": "crashed", "error": str(exc), "count": 0})

    raw_count = len(all_events)
    all_events = dedupe(all_events)
    deduped_count = len(all_events)
    all_events = sort_events(all_events)

    # Enrich: fix generic venue titles + generate tags
    for event in all_events:
        event["title"] = enrich_title(event)
        event["tags"] = tag_event(event)

    # Emit health summary
    total_ok = sum(1 for h in all_health if h["status"] == "ok")
    total_channels = len(all_health)
    health_summary = {
        "run_at": now.isoformat(),
        "window_days": window_days,
        "channels_ok": total_ok,
        "channels_total": total_channels,
        "raw_events": raw_count,
        "deduped_events": deduped_count,
        "channels": all_health,
    }

    EVENTS_FILE.write_text(json.dumps(all_events, indent=2, default=str))
    HEALTH_FILE.write_text(json.dumps(health_summary, indent=2))

    log.info("=== Done: %d raw → %d deduped events | %d/%d channels ok ===",
             raw_count, deduped_count, total_ok, total_channels)
    log.info("Output: %s", EVENTS_FILE)

    # Print health line for CI visibility
    print(f"\nHEALTH: {total_ok}/{total_channels} channels ok | {deduped_count} events | run at {now.isoformat()}")
    for h in all_health:
        status = h["status"]
        count = h.get("count", "?")
        err = f" — {h['error']}" if "error" in h else ""
        print(f"  [{status.upper():5}] {h['source']}: {count} events{err}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Bay Area Kids Events Scraper")
    parser.add_argument("--days", type=int, default=16, help="Rolling window in days (default 16)")
    args = parser.parse_args()
    main(args.days)
