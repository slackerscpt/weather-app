# Weather High Tracker

Logs the daily high temperature for any location to a CSV file (and optionally a Google Sheet). Weather data and place-name lookup come from [Open-Meteo](https://open-meteo.com/), which is free and needs no API key.

## Files

- `weather_high_tracker.py` – the app
- `Dockerfile` – container definition
- `docker-compose.yml` – maps `./data` on your machine to `/data` in the container
- `requirements.txt` – Python dependencies (`requests`, `gspread`, `tzdata`)

## Quick start (Docker)

Put all the files in one folder and run these from there. You need Docker with Compose (included in Docker Desktop).

```
docker compose run --rm weather
```

That's the whole command. The first run builds the image automatically, and your results are saved to `./data/weather_highs.csv` (the `data` folder is created for you).

The app asks you:

1. **Location** – e.g. `Paris, France` or `Portland, Oregon`. If several places match, pick one from the numbered list.
2. **Start date** – enter a date (`2026-01-15`), a number of days back (`30` = last 30 days, `365` = last year), or press Enter for just yesterday.
3. **End date** – only asked if your start date is earlier than yesterday. Press Enter for yesterday, or type a date.
4. **Save file** – press Enter to accept the default (`/data/weather_highs.csv`, which is `./data/weather_highs.csv` on your machine).

After you change `weather_high_tracker.py`, rebuild with `docker compose build` (or add `--build` to the run command).

## Skipping the prompts (options)

Anything you add after `weather` is used instead of asking. This is also how you run it on a schedule.

| Option | Description |
| --- | --- |
| `--location "City, State"` | Place name to look up. Omit to be prompted. |
| `--lat`, `--lon` | Coordinates (skips the place lookup). |
| `--label "Name"` | Name stored with `--lat`/`--lon`. |
| `--start YYYY-MM-DD` | First date to fetch. Omit to be prompted (default without a terminal: yesterday). |
| `--end YYYY-MM-DD` | Last date to fetch (default: same as start). Must be the location's last full day or earlier. |
| `--unit fahrenheit\|celsius` | Temperature unit (default: fahrenheit). |
| `--csv PATH` | Where to save (default: `/data/weather_highs.csv`; asked if omitted). |
| `--sheet "Sheet Name"` | Also write to this Google Sheet. |

Examples:

```
# Named location, yesterday's high
docker compose run --rm weather --location "Tokyo"

# A full year for one location
docker compose run --rm weather --location "Denver, Colorado" --start 2025-11-08 --end 2026-11-07

# Exact coordinates
docker compose run --rm weather --lat 40.71 --lon -74.01 --label "New York"
```

## Output format

`data/weather_highs.csv`:

```
date,location,high_F
2026-01-01,"Denver, Colorado, US",34.2
```

- Each day's high is based on the location's own local time, and "yesterday" is the location's last full day.
- Re-running is safe: a date + location already in the file is skipped.
- You can track multiple locations in the same file.
- If you have a CSV from an earlier version without a `location` column, rename or delete it first (or use `--csv` with a new filename).

## Google Sheets (optional)

1. In Google Cloud, create a service account, enable the **Google Sheets API** and **Google Drive API**, and download its JSON key.
2. Save the key as `data/service_account.json`.
3. Create a Google Sheet and share it with the service account's email address (Editor access).
4. Run with `--sheet`:

```
docker compose run --rm weather --sheet "Your Sheet Name"
```

The sheet gets the same `date`, `location`, `high` columns, and duplicates are skipped.

## Run it daily

A scheduled job has no one to answer prompts, so always pass `--location` (or `--lat`/`--lon`) and add `-T` to turn off the terminal. With no `--start`, it logs yesterday.

**cron (Mac/Linux)**, daily at 7 AM:

```
0 7 * * * cd /path/to/this/folder && docker compose run --rm -T weather --location "Tokyo"
```

**Windows:** create a Task Scheduler task that runs the same command from this folder.

## Running without Docker

```
pip install -r requirements.txt
python weather_high_tracker.py
```

Prompts and options work the same. The default save file is `weather_highs.csv` in the current folder.

## Troubleshooting

- **`503 Service Unavailable` from Open-Meteo:** a temporary problem on their servers. The app retries automatically for up to about a minute; if it still fails it exits with a short message. Wait a few minutes and run it again.
- **"No location given":** the app had no terminal to ask you in (for example, you used `-T`). Run without `-T`, or pass `--location`.
