"""Convert a Kanji Grid timelapse export into a lean JSON file for the viewer.

The Kanji Grid add-on's timelapse export is a JSON array where every entry is a
full HTML page for one day. This script parses each page, keeps only the data
that matters per kanji and stores the days as deltas against the previous day.

Usage:
    python extract_kanji_data.py <timelapse_export.json> [output.json]

Writes the JSON file (default: kanji_timelapse.json) and a sibling .js file
that assigns the same data to window.KANJI_TIMELAPSE, so index.html can be
opened straight from disk without a web server.

Stray reviews listed in IGNORED_REVIEWS below are removed from the output.

Output schema:
{
  "version": 1,
  "deck": "WK",
  "kanji": "一丶丿...",             # every kanji ever shown, in first-seen order
  "colors": ["#fff", "#E62E2E", ...],  # tile background colors
  "palette": ["#E62E2E", ...],          # the Weak -> Strong key gradient
  "fields": ["kanji", "color", "interval", "score", "seen", "unseen"],
  "days": [
    {"date": "2025-10-06", "time": "02:06:55", "known": 0, "total": 2169,
     "changes": [k, c, ivl, score, seen, unseen, k, c, ...]}
  ]
}

"changes" is a flat list of 6-tuples for kanji whose tile differs from the day
before (the first day lists every tile):
  k       index into "kanji"
  c       index into "colors", or -1 when the kanji is not in that day's grid
  ivl     average interval in hundredths of a day, -1 when not reviewed yet
  score   score in hundredths (0-100), -1 when not reviewed yet
  seen    number of seen cards containing the kanji
  unseen  number of unseen cards containing the kanji
"""

import json
import re
import sys
from pathlib import Path

TILE_RE = re.compile(
    r'<div class="grid-item" style="background:(#[0-9A-Fa-f]+);" '
    r'title="Character: [^|"]*\| '
    r'(?:Avg Interval: ([\d.]+) \| Score: ([\d.]+) \| )?'
    r'Unseen: (\d+) \| Seen: (\d+)">'
    r'<span class="kanji-tile">(.*?)</span></div>'
)
DATE_RE = re.compile(r'<p style="text-align: center">for (\d\d)/(\d\d)/(\d{4}) ([\d:]+)</p>')
KNOWN_RE = re.compile(r'<h4>(\d+) of (\d+) Known')
DECK_RE = re.compile(r'Kanji Grid - (.*?)</div>')
PALETTE_RE = re.compile(r'linear-gradient\(90deg,([^)]*)\)')

ABSENT = (-1, -1, -1, 0, 0)

# Review activity to drop, as {"YYYY-MM-DD": "kanji"}. On that date these kanji
# turned "seen" without really being studied (stray review-log entries on a few
# vocab cards). They are shown as unseen from that date until their seen-card
# count grows past the count from that date, i.e. until real study starts.
IGNORED_REVIEWS = {
    "2025-10-07": "浴衣飢餓家畜死産",
}


def hundredths(value):
    return -1 if value is None or value == "" else round(float(value) * 100)


def parse_day(html):
    date = DATE_RE.search(html)
    known = KNOWN_RE.search(html)
    if not date or not known:
        raise ValueError("page is missing the date or the known count")
    dd, mm, yyyy, time = date.groups()
    tiles = TILE_RE.findall(html)
    if len(tiles) != html.count('class="grid-item"'):
        raise ValueError("some tiles did not match the expected format")
    return {
        "date": f"{yyyy}-{mm}-{dd}",
        "time": time,
        "known": int(known.group(1)),
        "total": int(known.group(2)),
        "tiles": tiles,
    }


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("kanji_timelapse.json")

    pages = json.loads(src.read_text(encoding="utf-8"))
    if not pages:
        sys.exit("the export contains no days")

    deck = DECK_RE.search(pages[0])
    palette = PALETTE_RE.search(pages[0])

    kanji, kanji_index = [], {}
    colors, color_index = [], {}
    previous = {}  # kanji index -> state tuple
    days = []
    hidden = {}  # kanji index -> seen count whose reviews are ignored
    hidden_days = 0

    def color_id(bg):
        c = color_index.setdefault(bg, len(colors))
        if c == len(colors):
            colors.append(bg)
        return c

    parsed = sorted((parse_day(page) for page in pages), key=lambda d: (d["date"], d["time"]))
    for day in parsed:
        current = {}
        for bg, ivl, score, unseen, seen, char in day.pop("tiles"):
            k = kanji_index.setdefault(char, len(kanji))
            if k == len(kanji):
                kanji.append(char)
            bg = bg.upper() if bg.lower() != "#fff" else "#fff"
            current[k] = (color_id(bg), hundredths(ivl), hundredths(score), int(seen), int(unseen))

        for char in IGNORED_REVIEWS.get(day["date"], ""):
            k = kanji_index.get(char)
            if k in current and current[k][3] > 0:
                hidden[k] = current[k][3]
            else:
                print(f"warning: {char} is not seen on {day['date']}, nothing to ignore")
        for k, seen_count in list(hidden.items()):
            state = current.get(k)
            if state is None or state[3] > seen_count:
                del hidden[k]  # real study started
                continue
            current[k] = (color_id("#fff"), -1, -1, 0, state[3] + state[4])
            day["known"] -= state[3] > 0
            hidden_days += 1

        changes = []
        for k in sorted(set(current) | set(previous)):
            state = current.get(k, ABSENT)
            if previous.get(k, ABSENT) != state or not days:
                changes.append(k)
                changes.extend(state)
        day["changes"] = changes
        days.append(day)
        previous = current

    data = {
        "version": 1,
        "deck": deck.group(1) if deck else "",
        "kanji": "".join(kanji),
        "colors": colors,
        "palette": palette.group(1).split(",") if palette else [],
        "fields": ["kanji", "color", "interval", "score", "seen", "unseen"],
        "days": days,
    }

    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    dst.write_text(text, encoding="utf-8")
    dst.with_suffix(".js").write_text(f"window.KANJI_TIMELAPSE = {text};\n", encoding="utf-8")

    changes = sum(len(d["changes"]) // 6 for d in days)
    print(f"{len(days)} days ({days[0]['date']} to {days[-1]['date']}), "
          f"{len(kanji)} kanji, {len(colors)} colors, {changes} tile changes")
    if hidden_days:
        print(f"ignored reviews: {hidden_days} kanji-days shown as unseen")
    print(f"wrote {dst} ({dst.stat().st_size / 1e6:.2f} MB) and {dst.with_suffix('.js')}")


if __name__ == "__main__":
    main()
