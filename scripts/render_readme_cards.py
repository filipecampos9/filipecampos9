"""Render every README card into cards/*.svg and refresh the README block.

    python scripts/render_readme_cards.py            # animated cards
    STATIC=1 python scripts/render_readme_cards.py   # final frame only, for screenshots

Reads config.json, data/contributions.json and data/repos.json.
Needs fonttools (for text measuring); Pillow only if config.portrait is set.

The cards are shown through <img>, so GitHub gives them no JavaScript, no
external CSS and no network. Everything a card needs is inside the file:
an inline <style> with CSS keyframes, SMIL <animate>/<set> for what CSS can't
do (gradient shine, number count-up), and fonts embedded as base64 WOFF.
Every animation is switched off under prefers-reduced-motion, and the exact
same rules are applied unconditionally in STATIC mode.
"""
from __future__ import annotations

import base64
import datetime as dt
import html
import io
import json
import os
import re
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "cards"
STATIC = os.environ.get("STATIC") == "1"

CFG = json.loads((ROOT / "config.json").read_text())
THEME = CFG["theme"]

# Page-level timeline: each card starts a little later than the one above it,
# so the profile plays from top to bottom.
T_HERO, T_TILES, T_ACTIVITY, T_REPOS, T_HEATMAP = 0.0, 0.5, 1.1, 2.0, 2.6


# ───────────────────────────── fonts & text ─────────────────────────────

FONTS = {  # key -> (file, css family)
    "d": ("display.woff", "CardDisplay"),
    "i": ("display-italic.woff", "CardItalic"),
    "s": ("sans.woff", "CardSans"),
    "sm": ("sans-medium.woff", "CardSansMedium"),
    "m": ("mono.woff", "CardMono"),
}
_loaded: dict[str, TTFont] = {}


def _font(key: str) -> TTFont:
    if key not in _loaded:
        _loaded[key] = TTFont(ROOT / "fonts" / FONTS[key][0])
    return _loaded[key]


def measure(text: str, key: str, size: float, tracking: float = 0.0) -> float:
    """Advance width of `text` in px (no kerning — close enough for layout)."""
    f = _font(key)
    cmap, hmtx, upm = f.getBestCmap(), f["hmtx"], f["head"].unitsPerEm
    width = sum(hmtx[cmap[ord(c)]][0] if ord(c) in cmap else upm * 0.5 for c in text)
    return width * size / upm + tracking * size * len(text)


def wrap(text: str, key: str, size: float, max_w: float, max_lines: int = 2) -> list[str]:
    words, lines, line = text.split(), [], ""
    for w in words:
        trial = f"{line} {w}".strip()
        if measure(trial, key, size) <= max_w or not line:
            line = trial
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while measure(lines[-1] + "…", key, size) > max_w and " " in lines[-1]:
            lines[-1] = lines[-1].rsplit(" ", 1)[0]
        lines[-1] += "…"
    return lines


def esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", THEME.get("thousands_sep", ","))


# ───────────────────────────── colour & css ─────────────────────────────

def _mix(a: str, b: str, t: float) -> str:
    """Blend hex colour a over b with weight t."""
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * t + y * (1 - t)):02x}" for x, y in zip(pa, pb))


def _vars(p: dict, brand: str) -> str:
    heat = [_mix(brand, p["card"], t) for t in (0.3, 0.52, 0.76, 1.0)]
    out = {**{k: v for k, v in p.items() if not k.startswith("_")}, "brand": brand}
    out.update({f"h{i + 1}": c for i, c in enumerate(heat)})
    return ";".join(f"--{k}:{v}" for k, v in out.items())


def theme_css() -> str:
    css = f"svg{{{_vars(THEME['light'], THEME['brand'])}}}"
    if "dark" in THEME:
        css += ("@media (prefers-color-scheme:dark){svg{"
                f"{_vars(THEME['dark'], THEME.get('brand_dark', THEME['brand']))}}}}}")
    return css


BASE_CSS = """
.bg{fill:var(--card);stroke:var(--line)}
.ink{fill:var(--ink)}.muted{fill:var(--muted)}.brand{fill:var(--brand)}.faint{fill:var(--faint)}
.l0{fill:var(--empty)}.l1{fill:var(--h1)}.l2{fill:var(--h2)}.l3{fill:var(--h3)}.l4{fill:var(--h4)}
.rule{stroke:var(--line);stroke-width:1}
.d{font-family:CardDisplay}.i{font-family:CardItalic}.s{font-family:CardSans}
.sm{font-family:CardSansMedium}.m{font-family:CardMono;letter-spacing:.14em}.m0{font-family:CardMono}
.fade{animation:fadeUp .8s cubic-bezier(.2,.7,.2,1) both}
.grow{transform-box:fill-box;transform-origin:50% 100%;animation:grow 1s cubic-bezier(.2,.85,.25,1) both}
.growx{transform-box:fill-box;transform-origin:0 50%;animation:growx 1.1s cubic-bezier(.2,.85,.25,1) both}
.pop{transform-box:fill-box;transform-origin:50% 50%;animation:pop .45s cubic-bezier(.3,1.6,.5,1) both}
.swing{transform-box:fill-box;transform-origin:50% 0;animation:swing 1.15s cubic-bezier(.25,.9,.3,1) both}
.appear{animation:appear .01s linear both}
.static-only{display:none}
@keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@keyframes grow{from{transform:scaleY(0)}}
@keyframes growx{from{transform:scaleX(0)}}
@keyframes pop{from{opacity:0;transform:scale(.3)}}
@keyframes swing{0%{opacity:0;transform:translateY(-12px) rotate(-5deg)}
55%{opacity:1;transform:translateY(2px) rotate(1.8deg)}78%{transform:rotate(-.7deg)}100%{transform:none}}
@keyframes appear{from{opacity:0}to{opacity:1}}
"""

# Final-frame rules: no CSS animation, SMIL-only elements hidden, static
# fallbacks shown. Under prefers-reduced-motion normally, always in STATIC mode.
STILL_CSS = "*{animation:none!important}.anim-only{display:none}.static-only{display:inline}"


def _subset_woff(key: str, chars: str) -> bytes:
    """Cut the (already ASCII-subset) font down to just this card's characters."""
    font = TTFont(ROOT / "fonts" / FONTS[key][0])
    opts = subset.Options()
    opts.flavor, opts.layout_features = "woff", ["kern", "liga", "lnum", "tnum"]
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=[ord(c) for c in chars])
    sub.subset(font)
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue()


def font_css(keys: set[str], chars: str) -> str:
    out = []
    for k in sorted(keys):
        file, family = FONTS[k]
        data = base64.b64encode(_subset_woff(k, chars)).decode()
        out.append(f"@font-face{{font-family:{family};"
                   f"src:url(data:font/woff;base64,{data}) format('woff')}}")
    return "".join(out)


def svg(w: int, h: int, body: str, label: str, defs: str = "") -> str:
    classes = {c for attr in re.findall(r'class="([^"]*)"', body) for c in attr.split()}
    used = {k for k in FONTS if k in classes or (k == "m" and "m0" in classes)}
    still = STILL_CSS if STATIC else f"@media (prefers-reduced-motion:reduce){{{STILL_CSS}}}"
    chars = "".join(sorted({c for t in re.findall(r">([^<]+)<", body) for c in html.unescape(t)} | {" "}))
    css = font_css(used, chars) + theme_css() + BASE_CSS.replace("\n", "") + still
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
            f'width="{w}" height="{h}" role="img" aria-label="{esc(label)}">'
            f"<title>{esc(label)}</title><style>{css}</style>"
            f"{f'<defs>{defs}</defs>' if defs else ''}{body}</svg>")


def bg(w: float, h: float, x: float = 0, y: float = 0, rx: int = 22) -> str:
    return f'<rect class="bg" x="{x + .5}" y="{y + .5}" width="{w - 1}" height="{h - 1}" rx="{rx}"/>'


def delay(t: float) -> str:
    return f'style="animation-delay:{t:.2f}s"'


def counter(value: int, x: float, y: float, cls: str, size: int, start: float,
            dur: float = 1.1, frames: int = 18) -> str:
    """Number that counts up. CSS can't change text, so each intermediate
    value is its own <text>, shown for one step by a SMIL <set>."""
    parts = []
    final_at = start
    if not STATIC and value > 0:
        step = dur / frames
        steps = []
        for i in range(frames - 1):
            t = i / (frames - 1)
            v = round(value * (1 - (1 - t) ** 3))  # ease-out
            steps.append(f'<text x="{x}" y="{y}" class="{cls}" font-size="{size}" visibility="hidden">'
                         f'{fmt(v)}<set attributeName="visibility" to="visible" '
                         f'begin="{start + i * step:.3f}s" dur="{step:.3f}s"/></text>')
        parts.append(f'<g class="anim-only">{"".join(steps)}</g>')
        final_at = start + (frames - 1) * step
    parts.append(f'<text x="{x}" y="{y}" class="{cls} appear" font-size="{size}" '
                 f'{delay(final_at)}>{fmt(value)}</text>')
    return "".join(parts)


# ───────────────────────────── data ─────────────────────────────

def load_days() -> tuple[dict[dt.date, int], dt.date]:
    raw = json.loads((ROOT / "data" / "contributions.json").read_text())
    days = {dt.date.fromisoformat(d["date"]): d["count"] for d in raw["days"]}
    today = min(dt.date.today(), max(days))
    return days, today


def stats(days: dict[dt.date, int], today: dt.date) -> dict:
    months = []
    y, m = today.year, today.month
    for _ in range(12):
        months.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    months.reverse()
    start = dt.date(months[0][0], months[0][1], 1)
    window = {d: c for d, c in days.items() if start <= d <= today}

    per_month = [sum(c for d, c in window.items() if (d.year, d.month) == ym) for ym in months]

    # Current streak: today may still be empty, so start from yesterday then.
    cur, d = 0, today if days.get(today, 0) else today - dt.timedelta(days=1)
    while days.get(d, 0) > 0:
        cur, d = cur + 1, d - dt.timedelta(days=1)
    longest = run = 0
    prev = None
    for d in sorted(days):
        contiguous = prev is not None and d - prev == dt.timedelta(days=1)
        run = (run + 1 if contiguous else 1) if days[d] > 0 else 0
        longest, prev = max(longest, run), d

    return {
        "months": months,
        "per_month": per_month,
        "total": sum(window.values()),
        "active": sum(1 for c in window.values() if c > 0),
        "span": (today - start).days + 1,
        "busiest": max(window.values(), default=0),
        "streak": cur,
        "longest": max(longest, cur),
    }


# ───────────────────────────── cards ─────────────────────────────

def ascii_portrait(path: Path, cols: int = 56) -> list[str]:
    from PIL import Image, ImageOps  # only needed when a portrait is set
    ramp = " .:-=+*#%@"
    img = ImageOps.grayscale(Image.open(path))
    rows = max(1, round(cols * img.height / img.width * 0.5))
    img = ImageOps.autocontrast(img.resize((cols, rows)))
    px = img.load()
    return ["".join(ramp[(255 - px[x, y]) * (len(ramp) - 1) // 255] for x in range(cols))
            for y in range(rows)]


def card_hero() -> str:
    W, pad = 1000, 56
    portrait = CFG.get("portrait")
    art = ascii_portrait(ROOT / portrait) if portrait and (ROOT / portrait).exists() else []
    art_size, art_lh = 8.5, 9.5
    art_w = measure("M", "m", art_size) * (len(art[0]) if art else 0)
    text_w = W - 2 * pad - (art_w + 48 if art else 0)

    name = CFG["name"]
    name_size = 104
    while measure(name + ".", "d", name_size) > text_w and name_size > 48:
        name_size -= 4
    tag_lines = wrap(CFG.get("tagline", ""), "s", 23, text_w)

    y_kicker, y_name = 84, 84 + name_size * 0.95
    y_tag = y_name + 52
    y_sub = y_tag + 32 * (len(tag_lines) - 1) + 40
    H = int(max(y_sub + 52, (len(art) * art_lh + 2 * 48) if art else 0))

    b = [bg(W, H)]
    b.append(f'<text x="{pad}" y="{y_kicker}" class="m muted fade" font-size="13" {delay(T_HERO)}>'
             f'{esc(CFG.get("kicker", ""))}</text>')
    note = CFG.get("hero_note") or (re.sub(r"^https?://|/$", "", CFG["website"]) + " ↗"
                                     if CFG.get("website") else "")
    if not art and note:
        b.append(f'<text x="{W - pad}" y="{y_kicker}" text-anchor="end" class="m muted fade" '
                 f'font-size="13" {delay(T_HERO + .2)}>{esc(note.upper())}</text>')
    # Name: the animated copy is filled with a moving gradient (SMIL, since SVG
    # has no background-clip:text); the static copy is plain ink.
    for cls, fill in (("anim-only", 'fill="url(#shine)"'), ("static-only ink", "")):
        b.append(f'<text x="{pad - 4}" y="{y_name:.0f}" class="d fade {cls}" {fill} '
                 f'font-size="{name_size}" {delay(T_HERO + .1)}>{esc(name)}'
                 f'<tspan class="brand">.</tspan></text>')
    for i, line in enumerate(tag_lines):
        b.append(f'<text x="{pad}" y="{y_tag + i * 32:.0f}" class="s ink fade" font-size="23" '
                 f'{delay(T_HERO + .3 + i * .08)}>{esc(line)}</text>')
    if CFG.get("subline"):
        b.append(f'<text x="{pad}" y="{y_sub:.0f}" class="m muted fade" font-size="12.5" '
                 f'{delay(T_HERO + .45)}>{esc(CFG["subline"].upper())}</text>')
    if art:
        x0 = W - pad - art_w
        y0 = (H - len(art) * art_lh) / 2 + art_size
        for r, row in enumerate(art):
            b.append(f'<text x="{x0:.1f}" y="{y0 + r * art_lh:.1f}" class="m0 ink appear" '
                     f'font-size="{art_size}" xml:space="preserve" {delay(T_HERO + .3 + r * .035)}>'
                     f'{esc(row)}</text>')

    defs = ('<linearGradient id="shine" x1="0" x2="1" y1="0" y2="0">'
            '<stop offset="0" style="stop-color:var(--ink)"/><stop offset=".40" style="stop-color:var(--ink)"/>'
            '<stop offset=".5" style="stop-color:var(--brand)"/><stop offset=".60" style="stop-color:var(--ink)"/>'
            '<stop offset="1" style="stop-color:var(--ink)"/>'
            + ("" if STATIC else
               '<animateTransform attributeName="gradientTransform" type="translate" '
               'values="-1 0;1 0;1 0" keyTimes="0;.3;1" dur="7s" begin="0.5s" repeatCount="indefinite"/>')
            + "</linearGradient>")
    return svg(W, H, "".join(b), f"{name} — {CFG.get('tagline', '')}", defs)


def card_tile(tile: dict, idx: int) -> str:
    W, H, m = 320, 214, 10  # margin leaves room for the swing
    t0 = T_TILES + idx * .15
    x = m + 24
    b = [f'<g class="swing" {delay(t0)}>', bg(W - 2 * m, H - 2 * m, m, m, 20)]
    b.append(f'<text x="{x}" y="{m + 42}" class="m muted" font-size="12">{esc(tile["kicker"])}</text>')
    if tile.get("href"):
        b.append(f'<text x="{W - m - 24}" y="{m + 44}" text-anchor="end" class="m0 muted" font-size="17">↗</text>')
    y_big, size = m + 112, 62
    if "value" in tile:
        b.append(counter(int(tile["value"]), x - 2, y_big, "d ink", size, t0 + .35))
        big_w = measure(fmt(int(tile["value"])), "d", size)
    else:
        b.append(f'<text x="{x - 2}" y="{y_big}" class="d ink" font-size="{size}">{esc(tile["headline"])}</text>')
        big_w = measure(tile["headline"], "d", size)
    if tile.get("unit"):
        b.append(f'<text x="{x - 2 + big_w + 8:.1f}" y="{y_big}" class="i muted fade" font-size="30" '
                 f'{delay(t0 + .9)}>{esc(tile["unit"])}</text>')
    for i, line in enumerate(wrap(tile.get("caption", ""), "s", 15, W - 2 * m - 48)):
        b.append(f'<text x="{x}" y="{m + 150 + i * 21}" class="s muted" font-size="15">{esc(line)}</text>')
    b.append("</g>")
    label = f'{tile["kicker"]}: {tile.get("value", tile.get("headline", ""))} {tile.get("unit", "")} — {tile.get("caption", "")}'
    return svg(W, H, "".join(b), label)


def card_activity(s: dict) -> str:
    W, H, pad = 1000, 420, 52
    a = CFG.get("activity", {})
    t0 = T_ACTIVITY
    b = [bg(W, H)]
    b.append(f'<text x="{pad}" y="84" class="m muted fade" font-size="13" {delay(t0)}>'
             f'{esc(a.get("label", "THE LAST 12 MONTHS ON GITHUB"))}</text>')
    size = 70
    b.append(counter(s["total"], pad - 3, 156, "d ink", size, t0 + .1, dur=1.4))
    b.append(f'<text x="{pad - 3 + measure(fmt(s["total"]), "d", size) + 14:.1f}" y="156" '
             f'class="i ink fade" font-size="{size}" {delay(t0 + .2)}>'
             f'{esc(a.get("unit", "contributions"))}</text>')

    # Bars
    x0, x1, base, max_h = pad, 668, 344, 150
    slot = (x1 - x0) / 12
    bw = slot * .78
    peak = max(s["per_month"]) or 1
    peak_i = s["per_month"].index(peak)
    for i, ((yy, mm), v) in enumerate(zip(s["months"], s["per_month"])):
        h = max(4, v / peak * max_h)
        bx = x0 + i * slot
        cls = "faint" if i == 11 else ("brand" if i == peak_i else "ink")
        d = t0 + .35 + i * .06
        b.append(f'<rect x="{bx:.1f}" y="{base - h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="4" '
                 f'class="{cls} grow" {delay(d)}/>')
        if i == peak_i:
            b.append(f'<text x="{bx + bw / 2:.1f}" y="{base - h - 12:.1f}" text-anchor="middle" '
                     f'class="m0 brand fade" font-size="14" {delay(d + .7)}>{fmt(v)}</text>')
        b.append(f'<text x="{bx + bw / 2:.1f}" y="{base + 30}" text-anchor="middle" class="m0 muted fade" '
                 f'font-size="14" {delay(d)}>{dt.date(yy, mm, 1).strftime("%b")}</text>')

    # Stats column
    sx, sx1 = 724, W - pad
    streak_cap = ("current streak, and the longest" if s["streak"] >= s["longest"]
                  else f"current streak · longest {s['longest']}")
    rows = [
        (s["streak"], "days", None, streak_cap),
        (s["active"], None, f" / {s['span']}", "days with a contribution"),
        (s["busiest"], None, None, "on the busiest day"),
    ]
    for r, (num, unit, rest, cap) in enumerate(rows):
        y = 132 + r * 108
        d = t0 + .5 + r * .2
        b.append(counter(num, sx, y, "d ink", 54, d, dur=1.0))
        nx = sx + measure(fmt(num), "d", 54)
        if unit:
            b.append(f'<text x="{nx + 10:.1f}" y="{y}" class="i ink fade" font-size="54" {delay(d + .2)}>{unit}</text>')
        if rest:
            b.append(f'<text x="{nx + 4:.1f}" y="{y}" class="d muted fade" font-size="54" xml:space="preserve" '
                     f'{delay(d + .2)}>{esc(rest)}</text>')
        b.append(f'<text x="{sx}" y="{y + 32}" class="s muted fade" font-size="16" {delay(d + .1)}>{esc(cap)}</text>')
        if r < 2:
            b.append(f'<line x1="{sx}" x2="{sx1}" y1="{y + 62}" y2="{y + 62}" class="rule growx" '
                     f'{delay(d + .3)}/>')
    label = (f"{fmt(s['total'])} contributions in the last 12 months; {s['streak']}-day streak; "
             f"{s['active']} of {s['span']} days active; busiest day {s['busiest']}")
    return svg(W, H, "".join(b), label)


def card_repo(repo: dict, idx: int) -> str:
    W, pad = 1000, 52
    t0 = T_REPOS + idx * .25
    desc = wrap(repo.get("description") or "", "s", 17, W - 2 * pad)
    H = 196 + 26 * (len(desc) - 1)
    b = [bg(W, H)]
    b.append(f'<text x="{pad}" y="62" class="m muted fade" font-size="12.5" {delay(t0)}>'
             f'FEATURED REPO · {idx + 1:02d}</text>')

    # Right-hand meta, laid out right to left.
    x = W - pad
    meta = []
    forks = repo.get("forkCount", 0)
    for txt in ("↗", f"{fmt(forks)} fork{'' if forks == 1 else 's'}", f"★ {fmt(repo.get('stargazerCount', 0))}"):
        meta.append(f'<text x="{x:.1f}" y="62" text-anchor="end" class="m0 muted" font-size="14">{esc(txt)}</text>')
        x -= measure(txt, "m", 14) + 26
    lang = repo.get("primaryLanguage") or {}
    if lang.get("name"):
        meta.append(f'<text x="{x:.1f}" y="62" text-anchor="end" class="m0 muted" font-size="14">{esc(lang["name"])}</text>')
        x -= measure(lang["name"], "m", 14) + 12
        meta.append(f'<circle cx="{x:.1f}" cy="57" r="5" fill="{esc(lang.get("color") or "#888")}"/>')
    b.append(f'<g class="fade" {delay(t0 + .15)}>{"".join(meta)}</g>')

    b.append(f'<text x="{pad - 2}" y="118" class="d ink fade" font-size="48" {delay(t0 + .1)}>{esc(repo["name"])}</text>')
    b.append(f'<rect x="{pad}" y="132" width="44" height="3" rx="1.5" class="brand growx" {delay(t0 + .35)}/>')
    for i, line in enumerate(desc):
        b.append(f'<text x="{pad}" y="{166 + i * 26}" class="s muted fade" font-size="17" '
                 f'{delay(t0 + .25 + i * .06)}>{esc(line)}</text>')
    return svg(W, H, "".join(b), f"{repo['name']}: {repo.get('description') or ''}")


def card_heatmap(days: dict[dt.date, int], today: dt.date) -> str:
    W, H, cell, gap = 1000, 304, 13, 3
    hm = CFG.get("heatmap", {})
    t0 = T_HEATMAP
    pitch = cell + gap
    x0 = (W - 53 * pitch + gap) / 2
    y0 = 130
    first = today - dt.timedelta(days=(today.weekday() + 1) % 7 + 52 * 7)  # a Sunday

    counts = sorted(c for d, c in days.items() if first <= d <= today and c > 0)
    q = [counts[int(len(counts) * f)] for f in (.25, .5, .75)] if counts else [1, 2, 3]

    def level(c: int) -> int:
        return 0 if c == 0 else 1 + sum(c > t for t in q)

    b = [bg(W, H)]
    b.append(f'<text x="{x0 - 2:.1f}" y="92" class="d ink fade" font-size="46" {delay(t0)}>'
             f'{esc(hm.get("title", "Every day,"))} <tspan class="i brand">{esc(hm.get("title_accent", "in blue"))}</tspan></text>')
    b.append(f'<text x="{W - x0:.1f}" y="88" text-anchor="end" class="m muted fade" font-size="12.5" '
             f'{delay(t0 + .1)}>{esc(hm.get("label", "REFRESHED DAILY"))}</text>')

    # Legend geometry first, so month labels can stay clear of it.
    legend_w = measure("less", "m", 13) + 8 + 5 * pitch - gap + 8 + measure("more", "m", 13)
    legend_x = W - x0 - legend_w
    last_label_col = -9
    cells = []
    for col in range(53):
        for row in range(7):
            d = first + dt.timedelta(days=col * 7 + row)
            if d > today:
                continue
            label_x = x0 + col * pitch
            if (row == 0 and d.day <= 7 and col - last_label_col > 3
                    and label_x + measure("Mmm", "m", 13) < legend_x - 12):
                b.append(f'<text x="{x0 + col * pitch:.1f}" y="{y0 + 7 * pitch + 22}" class="m0 muted fade" '
                         f'font-size="13" {delay(t0 + .2)}>{d.strftime("%b")}</text>')
                last_label_col = col
            n = col * 7 + row
            cells.append(f'<rect x="{x0 + col * pitch:.1f}" y="{y0 + row * pitch}" width="{cell}" height="{cell}" '
                         f'rx="3" class="l{level(days.get(d, 0))} pop" {delay(t0 + .25 + n * .004)}/>')
    b.extend(cells)

    # Legend: less ■■■■■ more
    ly = y0 + 7 * pitch + 12
    x = W - x0
    b.append(f'<text x="{x:.1f}" y="{ly + 10}" text-anchor="end" class="m0 muted" font-size="13">more</text>')
    x -= measure("more", "m", 13) + 8 + 5 * pitch - gap
    for lv in range(5):
        b.append(f'<rect x="{x + lv * pitch:.1f}" y="{ly}" width="{cell}" height="{cell}" rx="3" class="l{lv}"/>')
    b.append(f'<text x="{x - 8:.1f}" y="{ly + 10}" text-anchor="end" class="m0 muted" font-size="13">less</text>')
    return svg(W, H, "".join(b), f"Contribution graph for the last year, updated {today.isoformat()}")


# ───────────────────────────── README ─────────────────────────────

START, END = "<!-- cards:start -->", "<!-- cards:end -->"


def readme_block(tiles: list[dict], repos: list[dict]) -> str:
    def img(src: str, alt: str, width: str = "100%", href: str | None = None) -> str:
        tag = f'<img src="./cards/{src}" width="{width}" alt="{esc(alt)}" />'
        return f'<a href="{esc(href)}">{tag}</a>' if href else tag

    parts = [img("hero.svg", CFG["name"], href=CFG.get("website")),
             "\n".join(img(f"tile-{i + 1}.svg", t["kicker"], "32.5%", t.get("href")) for i, t in enumerate(tiles)),
             img("activity.svg", "GitHub activity over the last 12 months")]
    parts += [img(f"repo-{slug(r['name'])}.svg", r["name"], href=r.get("url")) for r in repos]
    parts.append(img("heatmap.svg", "Contribution graph"))
    return "\n\n".join(parts)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def write_readme(block: str) -> None:
    path = ROOT / "README.md"
    wrapped = f"{START}\n{block}\n{END}"
    text = path.read_text() if path.exists() else ""
    if START in text and END in text:
        text = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: wrapped, text, flags=re.S)
    else:
        text = wrapped + "\n" + text
    path.write_text(text)


def write_preview(block: str) -> None:
    """A GitHub-width page for checking layout (and for headless screenshots)."""
    body = "".join(f"<p>{p}</p>" for p in block.split("\n\n"))
    (ROOT / ".preview").mkdir(exist_ok=True)
    (ROOT / ".preview" / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><base href='../'>"
        "<style>body{margin:0;background:#fff;font:16px system-ui}"
        "main{max-width:830px;margin:24px auto;padding:0 24px}p{margin:0 0 16px;line-height:0}"
        "img{max-width:100%}@media (prefers-color-scheme:dark){body{background:#0d1117}}</style>"
        f"<main>{body}</main>")


def main() -> None:
    CARDS.mkdir(exist_ok=True)
    days, today = load_days()
    s = stats(days, today)
    repos_file = ROOT / "data" / "repos.json"
    repos = json.loads(repos_file.read_text()) if repos_file.exists() else []
    tiles = CFG.get("tiles", [])[:3]

    out = {"hero.svg": card_hero(), "activity.svg": card_activity(s), "heatmap.svg": card_heatmap(days, today)}
    out.update({f"tile-{i + 1}.svg": card_tile(t, i) for i, t in enumerate(tiles)})
    out.update({f"repo-{slug(r['name'])}.svg": card_repo(r, i) for i, r in enumerate(repos)})

    for old in CARDS.glob("repo-*.svg"):
        if old.name not in out:
            old.unlink()
    for name, content in out.items():
        (CARDS / name).write_text(content)
        print(f"cards/{name:28} {len(content) / 1024:6.1f} KB")

    block = readme_block(tiles, repos)
    write_readme(block)
    write_preview(block)
    print(f"README updated{' (STATIC mode)' if STATIC else ''}.")


if __name__ == "__main__":
    main()
