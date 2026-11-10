# Kanji Grid Timelapse

A day-by-day timelapse of my Anki kanji progress, in the style of the
[Kanji Grid](https://ankiweb.net/shared/info/1610304449) add-on.

Open `index.html` locally, or view it on GitHub Pages.

## Files

- `index.html` – the viewer. It loads `kanji_timelapse.js`, so it works straight
  from disk without a web server; another `kanji_timelapse.json` can be dropped
  onto it.
- `fetch_kanji_data.py` – builds the data from Anki (standard library only).
- `kanji_timelapse.json` / `kanji_timelapse.js` – the generated data, committed
  so GitHub Pages can serve it. Both hold the same content.

## Updating the data

Requirements: Python 3, Anki running, and the
[AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on installed.

1. Pull the data straight from Anki (takes about 10 seconds):

   ```bash
   python fetch_kanji_data.py
   ```

2. Commit and push `kanji_timelapse.json` and `kanji_timelapse.js`.

The script only reads from Anki. It fetches the deck's cards, notes and review
log over AnkiConnect, then recomputes the grid for every day the same way Kanji
Grid's "time travel" does: a card counts with the interval of its last review
before that day's snapshot, and a kanji's color comes from the average interval
of the seen cards containing it. Cards that are new in Anki right now count as
unseen on every day, also if they were reviewed before being reset.

## Settings

The defaults are constants at the top of `fetch_kanji_data.py`; each has a
command-line option (`python fetch_kanji_data.py --help`).

| Option | Default | Meaning |
| --- | --- | --- |
| `output` | `kanji_timelapse.json` | Output file; the `.js` twin is written next to it |
| `--deck` | `WK` | Deck to read, subdecks included |
| `--field` | `Characters` | Note field holding the kanji (repeatable) |
| `--filter` | `-tag:radical` | Extra Anki search terms |
| `--interval` | `180` | Card interval (days) considered strong |
| `--start` | day of the first review | First day, `YYYY-MM-DD` |
| `--end` | today | Last day, `YYYY-MM-DD` |
| `--time` | `02:26:58` | UTC time of day each daily snapshot is taken at |
| `--url` | `http://127.0.0.1:8765` | AnkiConnect address |

Things to know:

- A day shows the state at that day's snapshot time, so reviews done after it
  appear on the next day, and today's reviews only show up tomorrow.
- `IGNORED_REVIEWS` lists stray reviews to drop, as `{"YYYY-MM-DD": "kanji"}`:
  those kanji stay unseen from that date until real study starts.
- The colors (`GRADIENT`, `UNSEEN_COLOR`) are Kanji Grid's defaults.
- The output format is documented in the docstring of the script.

## GitHub Pages

Settings → Pages → Build and deployment → Source: *Deploy from a branch*,
branch `main`, folder `/ (root)`.
