# Pillow (`PIL.Image` / `PIL.ImageDraw` / `PIL.ImageFont`) — API digest for the Billing capture PNG (issue #35, M7 slice 4)

> **Superseded by ADR 0017 (issue #38, 2026-08-22): nothing in `app/` renders with Pillow any
> more.** `capture/png.py` (the renderer this digest documents) was retired — the Billing capture
> `.png` is now a headless screenshot of the running Billing page (`capture/screenshot.py`). Pillow
> itself is **still in the tree**, as a transitive dependency of `fpdf2` (which hard-requires it),
> so this digest is kept for history rather than deleted — do not use it to justify writing new
> Pillow rendering code.

Written 2026-08-22, before the third capture renderer was implemented. Every signature below was
read directly out of the **installed** package at
`app/.venv/Lib/site-packages/PIL/` — Pillow **12.3.0** — either by running the snippet shown or
by `inspect.signature(...)` against the installed classes/functions, never from the web (which
may describe a different version) and never from memory. Follow the shape of
`docs/lib-notes/fpdf2-and-openpyxl.md`: facts first, then signatures, ⚠️ marking anything that
has moved since an older Pillow.

Confirmed installed version and build:

```python
>>> import PIL; PIL.__version__
'12.3.0'
>>> from PIL import features; features.version_module("freetype2")
'2.14.3'
>>> features.check("raqm")
False
```

FreeType is compiled in (real scalable TrueType text is available). `raqm` (complex text
shaping — bidi, ligatures) is **not** available — irrelevant here, the image is English-only,
same rule as `capture/pdf.py`.

Pillow itself is **pure Python plus a compiled C extension** (`_imaging`) that ships as a
prebuilt wheel — no Cairo, no Pango, no Chromium, and it needs nothing extra from PyInstaller
onedir packaging (it is already bundled transitively through `fpdf2`, per ADR 0014). This is
the same "no native ext to worry about at packaging time" property `fpdf2`/`openpyxl` have.

---

## The document lifecycle this renderer uses

```python
import io
from PIL import Image, ImageDraw, ImageFont

img = Image.new("RGB", (width, height), "#ffffff")
draw = ImageDraw.Draw(img)
font = ImageFont.load_default(size=14)
draw.rectangle([x0, y0, x1, y1], fill="#0f766e")
draw.text((x, y), "Hello", font=font, fill="#ffffff")
buffer = io.BytesIO()
img.save(buffer, format="PNG")
return buffer.getvalue()
```

`Image.new(...)` builds a fresh canvas; there is no reset, matching `fpdf2`'s "build one, output
it, throw it away" pattern.

### `Image.new`

```python
Image.new(mode: str, size: tuple[int, int] | list[int], color: float | tuple[float, ...] | str | None = 0) -> Image
```

`mode="RGB"` is what this renderer uses (no alpha needed). `color` accepts a hex string
(`"#ffffff"`) or an RGB tuple. `size` is `(width, height)` in pixels — there is no "auto-size"
mode; the caller must compute the canvas size in advance (measured from text, per below) before
calling this.

### `ImageDraw.Draw`

```python
ImageDraw.Draw(im: Image.Image, mode: str | None = None) -> ImageDraw
```

One `ImageDraw` object per image; every draw call below is a method on it.

### `ImageFont.load_default` — the in-memory font D9 rests on

```python
ImageFont.load_default(size: float | None = None) -> FreeTypeFont | ImageFont
```

Confirmed by running:

```python
>>> from PIL import ImageFont
>>> f = ImageFont.load_default(size=20)
>>> type(f).__name__, f.path
('FreeTypeFont', <_io.BytesIO object at 0x...>)
```

- With **no `size` argument** (or `size=None`), it returns a fixed small bitmap `ImageFont` — not
  scalable.
- **With `size=<float>` given**, it returns a real **`FreeTypeFont`**, backed by a **`BytesIO`
  object**, not a path on disk — the TrueType face is embedded as bytes inside the PIL package
  itself. `f.path` is a `_io.BytesIO` instance, confirming there is no filesystem read at all.
  This is exactly what makes `ImageFont.load_default(size=...)` safe to call inside the frozen
  `arichds.exe` on a customer machine: it cannot fail on a missing font file, because there is no
  file. There is a single face at any requested size — no separate bold/italic weight — so this
  renderer emphasises header rows with a fill colour and white text rather than a synthesised
  bold (never double-drawing to fake bold, per D9).

### `text` / `textlength` / `textbbox` — measurement, not estimation

```python
ImageDraw.text(self, xy: tuple[float, float], text: str, fill=None, font=None, anchor: str | None = None,
                spacing: float = 4, align: str = "left", ...) -> None

ImageDraw.textlength(self, text: str, font=None, direction=None, features=None, language=None,
                      embedded_color=False, *, font_size: float | None = None) -> float

ImageDraw.textbbox(self, xy: tuple[float, float], text: str, font=None, anchor: str | None = None,
                    spacing: float = 4, align: str = "left", direction=None, features=None,
                    language=None, stroke_width=0, embedded_color=False, *,
                    font_size: float | None = None) -> tuple[float, float, float, float]
```

- `textlength(text, font=font)` returns the advance width of *text* in pixels under *font* — used
  to size each column to its widest cell rather than guessing a fixed pixel width per character.
- `textbbox((x, y), text, font=font)` returns `(left, top, right, bottom)` — the actual ink
  bounding box at that anchor position; `bottom - top` gives a line's rendered height. Confirmed:

  ```python
  >>> draw.textbbox((0, 0), "Hello World", font=font)
  (0, 3, 74, 14)
  >>> draw.textlength("Hello World", font=font)
  74.0
  ```

  (font size 14, default `anchor` — top-left origin.)
- `anchor`: a two-character code (`"la"` = left/ascender the default, `"mm"` = middle/middle,
  etc.) controlling which point of the text box `xy` refers to. Not needed for this renderer —
  every cell is drawn from its top-left corner, matching `textbbox`'s default anchor, so widths
  and positions computed from `textbbox`/`textlength` line up with what `text()` actually draws
  without also having to reason about a non-default anchor.

### `rectangle` / `line` — the grid and header band

```python
ImageDraw.rectangle(self, xy: Coords, fill=None, outline=None, width: int = 1) -> None
ImageDraw.line(self, xy: Coords, fill=None, width: int = 1, joint: str | None = None) -> None
```

`xy` for `rectangle` is `[x0, y0, x1, y1]` (or a flat 4-tuple) — both corners inclusive. Used for
the teal header band (`fill="#0f766e"`) and for each ruled cell border (`outline=<light grey>`).
`line` is used for the plain horizontal/vertical grid rules where a full rectangle outline is not
needed.

### Saving to `BytesIO` as PNG

```python
buffer = io.BytesIO()
img.save(buffer, format="PNG")
data = buffer.getvalue()
```

Confirmed round-trip:

```python
>>> buf.getvalue()[:8]
b'\x89PNG\r\n\x1a\n'          # the PNG magic bytes
>>> Image.open(io.BytesIO(buf.getvalue())).format
'PNG'
```

Never touches the filesystem — mirrors `render_billing_pdf`/`render_billing_xlsx`'s own
"returns bytes, the caller does the hardened write" contract (`capture/write.py`).

---

## What this renderer does NOT use

No `ImageFont.truetype(...)` (a filesystem font path), no bundled `.ttf`/`.otf` file, no
`ImageDraw.textsize` (removed in newer Pillow; `textbbox`/`textlength` are the current
replacements — nothing here calls the old API so there is nothing to mark ⚠️ for it), no
`raqm`-dependent shaping features (`direction=`, complex `features=`).
