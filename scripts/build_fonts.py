"""Subset the source fonts into small WOFF files the cards can embed.

Run once (or whenever you change fonts):  python scripts/build_fonts.py
Needs:  pip install fonttools

Variable fonts are pinned to a single weight first, then every font is cut
down with pyftsubset to printable ASCII, Portuguese accents and a few symbols.
The name table of each output is printed, because a font file's *name* can lie
(an "Italic" file that is really the upright cut swaps styles silently).
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "fonts" / "src"
OUT = ROOT / "fonts"

# output name -> (source file, weight for variable fonts or None)
FONTS = {
    "display.woff": ("InstrumentSerif-Regular.ttf", None),
    "display-italic.woff": ("InstrumentSerif-Italic.ttf", None),
    "sans.woff": ("Geist-VF.ttf", 400),
    "sans-medium.woff": ("Geist-VF.ttf", 500),
    "mono.woff": ("GeistMono-VF.ttf", 400),
}

UNICODES = ",".join([
    "U+0020-007E",          # printable ASCII
    "U+00A0-00FF",          # Latin-1: á é í ó ú ã õ ç à â ê ô · « »
    "U+2013-2014",          # – —
    "U+2018-201D",          # ‘ ’ “ ”
    "U+2022", "U+2026",     # • …
    "U+2190-2199",          # arrows ← ↑ → ↓ ↗ ↘
    "U+2605",               # ★
])


def describe(path: Path) -> str:
    f = TTFont(path)
    name = f["name"]
    fam = name.getDebugName(1)
    sub = name.getDebugName(2)
    italic = bool(f["OS/2"].fsSelection & 1)
    return f"{fam} / {sub} (italic bit: {italic}, weight: {f['OS/2'].usWeightClass})"


def main() -> None:
    if not shutil.which("pyftsubset"):
        sys.exit("pyftsubset not found — pip install fonttools")
    with tempfile.TemporaryDirectory() as tmp:
        for out_name, (src_name, weight) in FONTS.items():
            src = SRC / src_name
            work = src
            if weight is not None:
                vf = TTFont(src)
                static = instancer.instantiateVariableFont(vf, {"wght": weight}, updateFontNames=True)
                work = Path(tmp) / f"{out_name}.ttf"
                static.save(work)
            out = OUT / out_name
            subprocess.run([
                "pyftsubset", str(work),
                f"--unicodes={UNICODES}",
                "--flavor=woff",
                "--layout-features=kern,liga,lnum,tnum",
                "--no-hinting", "--desubroutinize",
                f"--output-file={out}",
            ] + (["--with-zopfli"] if _has_zopfli() else []), check=True)
            print(f"{out_name:22} {out.stat().st_size/1024:5.1f} KB  {describe(out)}")


def _has_zopfli() -> bool:
    try:
        import zopfli  # noqa: F401
        return True
    except ImportError:
        return False


if __name__ == "__main__":
    main()
