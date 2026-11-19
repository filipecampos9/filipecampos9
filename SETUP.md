# README cards — setup

The profile README is a stack of animated SVG cards in `cards/`, rendered by
`scripts/render_readme_cards.py` and refreshed every morning by
`.github/workflows/readme-cards.yml`. This file isn't shown on your profile.

## First time

1. Create a public repo named exactly like your username (`USERNAME/USERNAME`) and push these files.
2. Edit `config.json`: `login`, `name`, tagline, `website`, the three tiles, the featured `repos`
   and the `theme` colours (light, dark, brand).
3. Repo **Settings → Actions → General → Workflow permissions** → *Read and write permissions*.
4. **Actions → Refresh README cards → Run workflow.** It replaces the sample data in `data/`
   with your real calendar and commits fresh cards.

Optional: add a fine-grained token as the `CARDS_TOKEN` secret if you want private
contributions / private repos counted (also turn on *Include private contributions*
in your GitHub profile settings).

## Working locally

```bash
pip install fonttools pillow
GH_TOKEN=ghp_xxx python scripts/fetch_data.py      # real data (optional)
STATIC=1 python scripts/render_readme_cards.py     # final frame only
google-chrome --headless --hide-scrollbars --window-size=880,1900 \
  --screenshot=preview.png .preview/index.html     # check before pushing
python scripts/render_readme_cards.py              # animated version — commit this one
```

Open `.preview/index.html` in a browser to watch the animation at GitHub's width.
Don't commit the STATIC render: the Action re-renders on push anyway.

## Files

| Path | What it is |
| --- | --- |
| `config.json` | All text, links, tiles, featured repos and colours |
| `scripts/render_readme_cards.py` | Renders every card + the README block between `<!-- cards:start/end -->` |
| `scripts/fetch_data.py` | GraphQL → `data/contributions.json`, `data/repos.json` |
| `scripts/build_fonts.py` | Pins/subsets `fonts/src/*` into `fonts/*.woff` with pyftsubset |
| `fonts/` | Instrument Serif (display), Geist (text), Geist Mono (labels) — all OFL |
| `assets/` | Optional portrait for the hero (`"portrait": "assets/me.jpg"`) — rendered as ASCII |

## How the cards work inside `<img>`

- No JS, no external CSS, no network. Each SVG carries its own `<style>`.
- CSS keyframes: fade-ups, bars growing from the baseline, tiles swinging in, heatmap squares popping.
- SMIL: `<animateTransform>` on a gradient for the shine on the name (SVG has no `background-clip:text`),
  `<set>` frames for the number count-ups (CSS can't change text).
- Fonts: each card embeds only the glyphs it uses, as base64 WOFF data URIs (cards are ~20–55 KB).
- Delays are offset per card (hero → tiles → activity → repos → heatmap) so the page plays top to bottom.
- `prefers-reduced-motion: reduce` turns every animation off and shows the final frame; `STATIC=1` applies the same rules unconditionally.
- `prefers-color-scheme: dark` switches to the dark palette. It follows the viewer's OS/browser setting,
  not GitHub's own theme toggle.

## Changing fonts

Drop new `.ttf` files in `fonts/src/`, update the `FONTS` map in `scripts/build_fonts.py`, run it, and check
the printed name table: a file called "Italic" that reports `italic bit: False` will silently swap styles.

GitHub caches images (camo), so a new render can take a few minutes to appear on the profile.
