"""Build the viewer's timelapse data straight from Anki through AnkiConnect.

The cards, notes and review log are pulled over AnkiConnect and the grid for
every day is recomputed the same way the Kanji Grid add-on's "time travel"
does it, so no Kanji Grid export is needed.

Anki has to be running with the AnkiConnect add-on (2055492159) installed.

Usage:
    python fetch_kanji_data.py [output.json] [options]

Run with --help for the options; the defaults below match my WK deck. Writes
the JSON file (default: kanji_timelapse.json) and a sibling .js file that
assigns the same data to window.KANJI_TIMELAPSE, so index.html can be opened
straight from disk without a web server.

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

import argparse
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

# Defaults; all of them can be overridden on the command line.
DECK = "WK"
FIELDS = ["Characters"]          # note fields the kanji are read from
SEARCH_FILTER = "-tag:radical"   # Kanji Grid's "Additional Search Filters"
STRONG_INTERVAL = 180            # Kanji Grid's "Card interval considered strong"
SNAPSHOT_TIME = "02:26:58"       # UTC time of day each daily snapshot is taken at
ANKI_CONNECT_URL = "http://127.0.0.1:8765"

# Kanji Grid's default colors.
GRADIENT = [
    "#e62e2e", "#e6442e", "#e65a2e", "#e6702e", "#e6872e", "#e69d2e", "#e6b32e",
    "#e6c92e", "#e6df2e", "#d8e62e", "#c2e62e", "#abe62e", "#95e62e", "#7fe62e",
    "#69e62e", "#53e62e", "#3de62e", "#2ee635", "#2ee64c", "#2ee662", "#2ee678",
    "#2ee68e", "#2ee6a4", "#2ee6ba", "#2ee6d0", "#2ee6e6",
]
UNSEEN_COLOR = "#fff"

ABSENT = (-1, -1, -1, 0, 0)

# Review activity to drop, as {"YYYY-MM-DD": "kanji"}. On that date these kanji
# turned "seen" without really being studied (stray review-log entries on a few
# vocab cards). They are shown as unseen from that date until their seen-card
# count grows past the count from that date, i.e. until real study starts.
IGNORED_REVIEWS = {
    "2025-10-07": "浴衣飢餓家畜死産",
}

CHUNK = 2000  # ids per AnkiConnect request
CJK_RE = re.compile("CJK (UNIFIED|COMPATIBILITY) IDEOGRAPH")


def anki(url, action, **params):
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            reply = json.load(response)
    except (urllib.error.URLError, ConnectionError) as error:
        sys.exit(f"cannot reach AnkiConnect at {url} ({error}); is Anki running?")
    if reply.get("error"):
        sys.exit(f"AnkiConnect {action} failed: {reply['error']}")
    return reply["result"]


def chunks(items):
    for i in range(0, len(items), CHUNK):
        yield items[i:i + CHUNK]


def is_kanji(char):
    return bool(CJK_RE.match(unicodedata.name(char, "")))


def score_adjust(score):
    score += 1
    return 1 - 1 / (score * score)


def gradient_color(score):
    last = len(GRADIENT) - 1
    start = int(score * last)
    end = min(start + 1, last)
    percent = score * last - start
    rgb = lambda color: [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    mixed = (round(a + (b - a) * percent) for a, b in zip(rgb(GRADIENT[start]), rgb(GRADIENT[end])))
    return "#" + "".join(f"{value:02X}" for value in mixed)


def fetch_cards(args):
    """Return [(card id, kanji, is new, review times, review intervals)] in card id order."""
    url = args.url
    fields = " OR ".join(f'"{field}:*"' for field in args.field)
    query = f'"deck:{args.deck}" ({fields}) {args.filter}'.strip()
    card_ids = sorted(anki(url, "findCards", query=query))
    if not card_ids:
        sys.exit(f"no cards match: {query}")
    new_cards = set(anki(url, "findCards", query=f"({query}) is:new"))
    print(f"{len(card_ids)} cards, fetching notes and reviews...")

    wanted = [field.lower() for field in args.field]
    kanji_of = {}  # card id -> kanji on its note
    for chunk in chunks(anki(url, "findNotes", query=query)):
        for note in anki(url, "notesInfo", notes=chunk):
            names = {name.lower(): name for name in reversed(note["fields"])}
            text = "".join(note["fields"][names[w]]["value"] for w in wanted if w in names)
            kanji = [c for c in dict.fromkeys(text) if is_kanji(c)]
            kanji_of.update((card_id, kanji) for card_id in note["cards"])

    # cardReviews dumps a whole deck's review log in one go, which is far faster
    # than getReviewsOfCards (that one slows down sharply with the number of cards).
    logs = {card_id: [] for card_id in card_ids}  # card id -> [(review time, interval)]
    decks = [d for d in anki(url, "deckNames") if d == args.deck or d.startswith(args.deck + "::")]
    for deck in decks:
        for review_id, card_id, _usn, _ease, ivl, *_ in anki(url, "cardReviews", deck=deck, startID=0):
            if card_id in logs:
                logs[card_id].append((review_id, ivl))
    # It only covers cards currently sitting in those decks, so reviewed cards it
    # missed (e.g. ones moved into a filtered deck) are looked up individually.
    missed = [c for c in card_ids if not logs[c] and c not in new_cards]
    for i in range(0, len(missed), 250):
        for card_id, reviews in anki(url, "getReviewsOfCards", cards=missed[i:i + 250]).items():
            logs[int(card_id)] = [(r["id"], r["ivl"]) for r in reviews]

    cards = []
    for card_id in card_ids:
        log = sorted(logs[card_id])
        cards.append((card_id, kanji_of.get(card_id, []), card_id in new_cards,
                      [r[0] for r in log], [r[1] for r in log]))
    return cards


def snapshot(cards, pointers, at_ms, interval):
    """The grid tiles as Kanji Grid would time-travel them to at_ms."""
    units = {}  # kanji -> [average interval, seen cards, unseen cards]
    for n, (card_id, kanji, is_new, times, intervals) in enumerate(cards):
        p = pointers[n]
        while p < len(times) and times[p] <= at_ms:
            p += 1
        pointers[n] = p
        if p == 0 and card_id > at_ms:
            continue  # the card did not exist yet
        seen = p > 0 and not is_new
        if seen:
            # a negative review-log interval is in seconds, a positive one in days
            ivl = intervals[p - 1]
            ivl = ivl if ivl >= 0 else -ivl // 86400
        for char in kanji:
            unit = units.setdefault(char, [0.0, 0, 0])
            if seen:
                unit[0] = (unit[0] * unit[1] + ivl) / (unit[1] + 1)
                unit[1] += 1
            else:
                unit[2] += 1

    ordered = sorted(units.items(), key=lambda u: (score_adjust(u[1][0] / interval), u[1][1]), reverse=True)
    tiles = []
    for char, (average, seen, unseen) in ordered:
        score = score_adjust(average / interval)
        tiles.append((
            gradient_color(score) if seen else UNSEEN_COLOR,
            f"{average:.2f}" if average else "",
            f"{score:.2f}" if average else "",
            unseen, seen, char,
        ))
    return tiles


def hundredths(value):
    return -1 if value is None or value == "" else round(float(value) * 100)


def build_and_write(parsed, deck, palette, dst):
    """Delta-encode the days and write the viewer's .json and .js files.

    parsed is a list of {"date", "time", "known", "total", "tiles"} dicts, where
    tiles holds (background, interval, score, unseen, seen, kanji) per tile, with
    interval and score as decimal strings or "" when not reviewed yet.
    """
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

    for day in sorted(parsed, key=lambda d: (d["date"], d["time"])):
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
        "deck": deck,
        "kanji": "".join(kanji),
        "colors": colors,
        "palette": palette,
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


def parse_date(text):
    return datetime.strptime(text, "%Y-%m-%d").date()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("output", nargs="?", default="kanji_timelapse.json", type=Path)
    parser.add_argument("--deck", default=DECK, help=f"deck name, subdecks included (default: {DECK})")
    parser.add_argument("--field", action="append",
                        help=f"note field holding the kanji, repeatable (default: {' '.join(FIELDS)})")
    parser.add_argument("--filter", default=SEARCH_FILTER,
                        help=f"extra Anki search terms (default: {SEARCH_FILTER})")
    parser.add_argument("--interval", default=STRONG_INTERVAL, type=int,
                        help=f"card interval considered strong, in days (default: {STRONG_INTERVAL})")
    parser.add_argument("--start", type=parse_date, help="first day, YYYY-MM-DD (default: day of the first review)")
    parser.add_argument("--end", type=parse_date, help="last day, YYYY-MM-DD (default: today)")
    parser.add_argument("--time", default=SNAPSHOT_TIME, type=time.fromisoformat,
                        help=f"UTC time of day of each snapshot (default: {SNAPSHOT_TIME})")
    parser.add_argument("--url", default=ANKI_CONNECT_URL, help=f"AnkiConnect address (default: {ANKI_CONNECT_URL})")
    args = parser.parse_args()
    args.field = args.field or FIELDS

    cards = fetch_cards(args)

    def at(day):
        return datetime.combine(day, args.time, timezone.utc)

    def last_snapshot_before(moment):
        day = moment.date()
        return day if at(day) <= moment else day - timedelta(days=1)

    first_review = min((times[0] for *_, times, _ in cards if times), default=None)
    if first_review is None and not args.start:
        sys.exit("no reviews found; pass --start to build a timelapse anyway")
    now = datetime.now(timezone.utc)
    start = args.start or last_snapshot_before(datetime.fromtimestamp(first_review / 1000, timezone.utc))
    end = min(args.end or now.date(), last_snapshot_before(now))
    if end < start:
        sys.exit(f"nothing to do: start {start} is after end {end}")

    pointers = [0] * len(cards)
    parsed = []
    day = start
    while day <= end:
        tiles = snapshot(cards, pointers, int(at(day).timestamp() * 1000), args.interval)
        parsed.append({
            "date": day.isoformat(),
            "time": args.time.isoformat(),
            "known": sum(1 for tile in tiles if tile[4]),
            "total": len(tiles),
            "tiles": tiles,
        })
        day += timedelta(days=1)

    palette = [gradient_color(i / 100) for i in range(101)]
    build_and_write(parsed, args.deck.rsplit("::", 1)[-1], palette, args.output)


if __name__ == "__main__":
    main()
