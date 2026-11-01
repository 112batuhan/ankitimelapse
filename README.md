# Kanji Grid Timelapse

A day-by-day timelapse of my Anki kanji progress, built from the
Kanji Grid add-on's timelapse export.

Open `index.html` locally, or view it on GitHub Pages.

## Updating the data

1. Export a timelapse from Kanji Grid into this folder (`timelapse_*.json`; these
   raw files are git-ignored because of their size).
2. Extract the lean data the viewer uses:

   ```bash
   python extract_kanji_data.py timelapse_<...>.json
   ```

   This writes `kanji_timelapse.json` and `kanji_timelapse.js`. Stray reviews
   to drop are listed in `IGNORED_REVIEWS` at the top of the script.
3. Commit and push `kanji_timelapse.json` and `kanji_timelapse.js`.

## GitHub Pages

Settings → Pages → Build and deployment → Source: *Deploy from a branch*,
branch `main`, folder `/ (root)`.
