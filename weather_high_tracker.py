#!/usr/bin/env python3
"""
Log the daily high temperature for any location to a CSV (and optionally a Google Sheet).

Data source: Open-Meteo (free, no API key) for both weather and place-name lookup.

Usage:
    python weather_high_tracker.py                          # asks for location and dates
    python weather_high_tracker.py --location "Paris, France"
    python weather_high_tracker.py --lat 40.71 --lon -74.01
    python weather_high_tracker.py --location "Denver, Colorado" --start 2026-01-01 --end 2026-01-31
    python weather_high_tracker.py --location "Tokyo" --sheet "Weather Tracker"

Re-running is safe: a date + location already in the file/sheet is skipped.
"Yesterday" is calculated in the chosen location's own time zone.
"""
import argparse
import csv
import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

UNIT = "fahrenheit"  # or "celsius"
CSV_PATH = os.environ.get("WEATHER_CSV", "weather_highs.csv")
CREDS_PATH = os.environ.get("WEATHER_CREDS", "service_account.json")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"  # also serves the last ~90 days
ARCHIVE_LAG_DAYS = 7


# ---------- HTTP ----------
def http_get(url, params):
    """GET with automatic retries (with backoff) for temporary server errors."""
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=2,  # waits 2s, 4s, 8s, 16s, 32s between attempts
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    try:
        resp = session.get(url, params=params, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        sys.exit(
            f"Could not get data from Open-Meteo ({e.__class__.__name__}). "
            "The service may be temporarily down; please try again in a few minutes."
        )
    return resp


def timezone_for(lat, lon):
    resp = http_get(
        FORECAST_URL,
        {"latitude": lat, "longitude": lon, "daily": "temperature_2m_max",
         "forecast_days": 1, "timezone": "auto"},
    )
    return resp.json()["timezone"]


# ---------- Location lookup ----------
def search_places(query):
    """Find places matching e.g. 'Paris', 'Portland, Oregon', or 'Paris, France'."""
    parts = [p.strip() for p in query.split(",") if p.strip()]
    if not parts:
        return []
    resp = http_get(
        GEOCODE_URL,
        {"name": parts[0], "count": 10, "language": "en", "format": "json"},
    )
    results = resp.json().get("results", [])

    # Narrow by anything after the comma (state/region/country)
    if len(parts) > 1:
        hints = [h.lower() for h in parts[1:]]
        narrowed = [
            r for r in results
            if all(
                any(h in str(r.get(k, "")).lower() for k in ("admin1", "admin2", "country", "country_code"))
                for h in hints
            )
        ]
        results = narrowed or results
    return results


def label_for(place):
    bits = [place["name"], place.get("admin1"), place.get("country_code")]
    return ", ".join(b for b in bits if b)


def choose_place(query):
    places = search_places(query)
    if not places:
        return None
    if len(places) == 1 or not sys.stdin.isatty():
        return places[0]
    print("\nMultiple matches found:")
    for i, p in enumerate(places, 1):
        print(f"  {i}. {label_for(p)}")
    while True:
        pick = input(f"Pick one [1-{len(places)}] (Enter for 1): ").strip() or "1"
        if pick.isdigit() and 1 <= int(pick) <= len(places):
            return places[int(pick) - 1]
        print("Invalid choice.")


def resolve_location(args):
    """Return (label, lat, lon, timezone)."""
    if args.lat is not None and args.lon is not None:
        return (args.label or f"{args.lat},{args.lon}", args.lat, args.lon,
                timezone_for(args.lat, args.lon))

    query = args.location
    while True:
        if not query:
            if not sys.stdin.isatty():
                sys.exit(
                    "No location given. Use --location \"City, State\" or --lat/--lon "
                    "(or run with `docker run -it` to be prompted)."
                )
            query = input("What location do you want weather for? (e.g. Paris, France): ").strip()
            if not query:
                continue
        place = choose_place(query)
        if place:
            print(f"Using: {label_for(place)}")
            lat, lon = place["latitude"], place["longitude"]
            return label_for(place), lat, lon, place.get("timezone") or timezone_for(lat, lon)
        print(f"No matches for '{query}'.")
        if not sys.stdin.isatty():
            sys.exit(1)
        query = None


# ---------- Weather ----------
def fetch_highs(lat, lon, start, end, unit, today):
    """Return {date_str: high_temp} for start..end inclusive."""
    cutoff = today - dt.timedelta(days=ARCHIVE_LAG_DAYS)
    ranges = []
    if start < cutoff:
        ranges.append((ARCHIVE_URL, start, min(end, cutoff - dt.timedelta(days=1))))
    if end >= cutoff:
        ranges.append((FORECAST_URL, max(start, cutoff), end))

    results = {}
    for url, s, e in ranges:
        resp = http_get(
            url,
            {
                "latitude": lat,
                "longitude": lon,
                "start_date": s.isoformat(),
                "end_date": e.isoformat(),
                "daily": "temperature_2m_max",
                "temperature_unit": unit,
                "timezone": "auto",  # each "day" is the location's local day
            },
        )
        daily = resp.json()["daily"]
        for day, temp in zip(daily["time"], daily["temperature_2m_max"]):
            if temp is not None:
                results[day] = temp
    return results


# ---------- Output ----------
def header(unit):
    return ["date", "location", f"high_{'F' if unit == 'fahrenheit' else 'C'}"]


def write_csv(path, label, highs, unit):
    existing = set()
    exists = os.path.exists(path)
    if exists:
        with open(path, newline="") as f:
            rows = list(csv.reader(f))
        if rows and "location" not in rows[0]:
            sys.exit(
                f"{path} uses the old format (no location column). "
                "Rename or delete it, or pass --csv with a new filename."
            )
        existing = {(r[0], r[1]) for r in rows[1:] if len(r) > 1}
    new_rows = [[d, label, t] for d, t in sorted(highs.items()) if (d, label) not in existing]
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(header(unit))
        w.writerows(new_rows)
    return len(new_rows)


def write_sheet(sheet_name, creds_path, label, highs, unit):
    import gspread  # only needed for Google Sheets

    ws = gspread.service_account(filename=creds_path).open(sheet_name).sheet1
    values = ws.get_all_values()
    if not values:
        ws.append_row(header(unit))
    existing = {(r[0], r[1]) for r in values[1:] if len(r) > 1}
    new_rows = [[d, label, t] for d, t in sorted(highs.items()) if (d, label) not in existing]
    if new_rows:
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")
    return len(new_rows)


# ---------- Date prompts ----------
def ask_start(yesterday):
    print("\nWhat start date do you want?")
    print("  - a date (YYYY-MM-DD), or")
    print("  - a number of days back (30 = last 30 days, 365 = last year), or")
    print("  - press Enter for just yesterday.")
    while True:
        raw = input("Start date: ").strip()
        if not raw:
            return yesterday
        try:
            if raw.isdigit() and int(raw) >= 1:
                start = yesterday - dt.timedelta(days=int(raw) - 1)
            else:
                start = dt.date.fromisoformat(raw)
        except ValueError:
            print("Please enter a date like 2026-01-15 or a number of days like 90.")
            continue
        if start > yesterday:
            print(f"Start date can't be after {yesterday} (the last full day there).")
            continue
        return start


def ask_end(yesterday, start):
    while True:
        raw = input(f"End date (YYYY-MM-DD) [Enter = {yesterday}]: ").strip()
        if not raw:
            return yesterday
        try:
            end = dt.date.fromisoformat(raw)
        except ValueError:
            print("Please enter a date like 2026-01-15.")
            continue
        if end > yesterday or end < start:
            print(f"End date must be between {start} and {yesterday}.")
            continue
        return end


def ask_csv_path(default):
    raw = input(f"\nWhich CSV file should the results be saved to? [Enter = {default}]: ").strip()
    return raw or default


def main():
    p = argparse.ArgumentParser(description="Log daily high temperatures for any location.")
    p.add_argument("--location", help='Place name, e.g. "Paris, France" (omit to be asked)')
    p.add_argument("--lat", type=float, help="Latitude (skips the place lookup)")
    p.add_argument("--lon", type=float, help="Longitude (skips the place lookup)")
    p.add_argument("--label", help="Name to store with --lat/--lon")
    p.add_argument("--unit", choices=["fahrenheit", "celsius"], default=UNIT)
    p.add_argument("--start", type=dt.date.fromisoformat, help="YYYY-MM-DD (default: yesterday)")
    p.add_argument("--end", type=dt.date.fromisoformat, help="YYYY-MM-DD (default: same as start)")
    p.add_argument("--csv", help=f"CSV output path (default: {CSV_PATH}; asked if omitted)")
    p.add_argument("--sheet", help="Google Sheet name (optional)")
    p.add_argument("--creds", default=CREDS_PATH, help="Google service account JSON")
    args = p.parse_args()

    label, lat, lon, tz = resolve_location(args)

    # "Today" and "yesterday" in the location's own time zone (containers run on UTC)
    today = dt.datetime.now(ZoneInfo(tz)).date()
    yesterday = today - dt.timedelta(days=1)
    interactive = sys.stdin.isatty()
    start = args.start
    if start is None and interactive:
        start = ask_start(yesterday)
    start = start or yesterday

    end = args.end
    if end is None and interactive and args.start is None and start < yesterday:
        end = ask_end(yesterday, start)
    end = end or start

    if end > yesterday:
        sys.exit(f"End date must be {yesterday} or earlier (the last full day in {label}).")
    if start > end:
        sys.exit("Start date must be on or before the end date.")

    csv_path = args.csv or (ask_csv_path(CSV_PATH) if interactive else CSV_PATH)
    folder = os.path.dirname(csv_path)
    if folder:
        os.makedirs(folder, exist_ok=True)

    highs = fetch_highs(lat, lon, start, end, args.unit, today)
    if not highs:
        sys.exit("No data returned for that range.")

    print(f"CSV: added {write_csv(csv_path, label, highs, args.unit)} new row(s) to {csv_path}")
    if args.sheet:
        print(f"Sheet: added {write_sheet(args.sheet, args.creds, label, highs, args.unit)} new row(s)")


if __name__ == "__main__":
    main()
