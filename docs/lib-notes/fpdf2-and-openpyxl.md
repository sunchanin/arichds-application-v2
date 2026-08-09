# fpdf2 & openpyxl — API digest for M6 billing capture

Written 2026-08-09, before M6 started. Both libraries are **new to v2** — nothing in
`app/pyproject.toml` pins them yet, and M6 is the first module that needs either.

**Where these facts come from.** Not from memory and not from the web: every signature below
was read out of the versions v1 actually runs against, in
`cewe/cewe-worker/.venv/Lib/site-packages/` — **fpdf2 2.8.7** and **openpyxl 3.1.5**. That is
the strongest source available, because v1's renderers are field-proven against exactly these
builds. Pin at or above them; if you pin higher, re-read the two signatures marked ⚠️ below,
which are the ones that have already moved once.

Both are **pure Python** — no Cairo, no Pango, no Chromium. That was the whole reason v1 chose
them (its ADR 0003 rejected a headless browser on install weight) and it is why PyInstaller
onedir packaging needs nothing special for either.

---

## fpdf2

```python
from fpdf import FPDF
```

### The document lifecycle v1 uses, verbatim

```python
pdf = FPDF(orientation="L", unit="mm", format="A4")
pdf.set_margins(margin, margin, margin)
pdf.set_auto_page_break(auto=True, margin=margin)
pdf.add_page()
pdf.set_font("Helvetica", "B", 14)
...
return bytes(pdf.output())
```

`FPDF` is instantiated per document. There is no reset — build one, output it, throw it away.

### ⚠️ `cell()` — `ln=` is deprecated, use `new_x` / `new_y`

```python
def cell(self, w=None, h=None, text="", border=0,
         ln="DEPRECATED",                      # ← passing this warns
         align=Align.L, fill=False, link="", center=False, markdown=False,
         new_x=XPos.RIGHT, new_y=YPos.TOP) -> bool
```

The library literally defaults `ln` to the string `"DEPRECATED"` and raises a warning naming
the replacement (`fpdf/fpdf.py:3904`). The two idioms v1 uses:

| Intent | Arguments |
|---|---|
| Finish the line, start the next at the left margin | `new_x="LMARGIN", new_y="NEXT"` |
| Stay on the same line, continue to the right | `new_x="RIGHT", new_y="TOP"` |

Strings are accepted as well as the `XPos`/`YPos` enums. A two-column `label | value` table row
is the first form followed by the second — that is the entire layout primitive v1's report
uses; there is no table widget involved.

Note the text parameter is named **`text`**, not `txt`. Older fpdf2 examples on the web use
`txt=` and it is gone.

### ⚠️ `output()` returns a `bytearray`, not `bytes`

```python
def output(self, name="", *, linearize=False, output_producer_class=OutputProducer) -> Optional[bytearray]
```

With no `name` it returns the buffer; with a `name` it writes the file and returns `None`.
v1 wraps it — `bytes(pdf.output())` — and M6 must too, because the bytes have to be rendered
**before** the file is opened (ADR 0003's orphan-prevention rule: render first, then
`os.open`, so a render failure cannot leave a partial file on disk).

Do **not** pass a path to `output()` in M6. The capture write path is hardened by hand
(stepwise `mkdir(mode=0o700)`, `lstat` for `S_ISLNK`, `os.open(O_NOFOLLOW)`) and letting fpdf2
open the file itself would bypass all of it.

### Other calls M6 needs

| Call | Note |
|---|---|
| `set_font(family, style, size)` | `"Helvetica"` is a built-in core font — no file, no embedding |
| `set_fill_color(r, g, b)` | Applies to subsequent `cell(fill=True)` |
| `ln(h)` | Vertical gap between sections |
| `pdf.w` | Page width — v1 computes column widths as `pdf.w - 2 * margin` |

### The Unicode decision, and why `add_font` is deliberately unused

`add_font()` exists (`fpdf/fpdf.py:2484`) and is how fpdf2 renders non-Latin text: register a
TTF, then select it. **M6 does not use it.** The owner decided at the M6 grill (2026-08-09)
that the document is English and that operator-entered values which are not ASCII are replaced
and logged, exactly as v1 does.

The consequence is concrete and is not a bug to be fixed later without a decision: a site whose
`site_name` is Thai renders as `?` in the capture. v1 encodes the same choice with a
module-level `lru_cache` that warns once per distinct name rather than once per render — worth
copying, since the alternative is a warning per capture per period forever.

---

## openpyxl

```python
from openpyxl import Workbook
```

### The whole API surface M6 needs

```python
wb = Workbook()
sheet = wb.active
sheet.title = "Billing"
sheet.append(["Device", name])     # one row; [] appends a blank row
...
buffer = io.BytesIO()
wb.save(buffer)
return buffer.getvalue()
```

That is genuinely all of it. `Workbook()` starts with one active sheet, `append()` takes a list
of cell values and writes the next row, and `save()` accepts a file-like object so nothing has
to touch the disk before the hardened write path does.

**openpyxl writes UTF-8 natively** — the ASCII-replacement rule above applies to the PDF only.
The two renderers therefore produce the same *content* but not always the same *characters*,
and that asymmetry is intended.

---

## The rule that keeps the two in step

v1 keeps section and field definitions in one shared module that both renderers import, rather
than declaring them twice, precisely so a field added to one cannot go missing from the other.
Copy that structure. The two capture formats are sold as separate features
(`auto_capture` and `billing_excel_export`), so a customer may hold one and not the other —
which makes silent drift between them the kind of bug nobody is positioned to notice.
