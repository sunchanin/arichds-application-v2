# The capture image is drawn, never screenshotted

> **Superseded by ADR 0017.** The capture PNG is now a headless screenshot of our own Billing
> page, driven over CDP against the already-installed Microsoft Edge — see
> `docs/adr/0017-the-capture-image-is-a-headless-screenshot-of-our-own-page.md`. This document is
> kept as the historical record of the decision it reverses; nothing below is edited.

The owner relayed a customer request in two clauses that cannot both be honoured literally:
*"capture จากหน้าจอจริงๆเลย"* and *"ต้องการให้มัน capture แบบ auto ได้ถึงแม้ว่าจะไม่ได้เปิดหน้า UI
ทิ้งเอาไว้"*. **When nobody is looking at the page there is no screen to photograph** — no
browser, no viewport, no session, no logged-in user. The unattended clause is the binding one,
so the image is always re-rendered on the server. This ADR records that we chose to draw it
with Pillow rather than drive a headless browser, and why "it does not look pixel-identical to
Chrome" is an accepted outcome rather than a defect to be fixed later.

## What the customer is actually complaining about

The existing Capture is a per-period summary document laid out by `capture/pdf.py`. The
customer's word for what they want instead is *"เหมือน capture หน้าจอมาจากโปรแกรมจริงๆ"* — the
teal header band, the grouped column headers, the ruled grid, the numbers in the same order the
Billing page shows them.

That is a description of **visual style**, not of a capture mechanism. Nothing in the request
depends on the bytes coming from a real framebuffer; it depends on the output looking like the
product rather than like a report. A drawn image can satisfy that. A screenshot is one way to
get it, not the requirement itself.

## Considered options

| | Bundle cost | Fidelity | Fits the stated constraints |
|---|---|---|---|
| **Pillow, drawing the table** | **0 MB** — already bundled | Same palette, fonts, grid; not pixel-identical | ✅ |
| Headless Chromium (Playwright) | 35 MB → ~250 MB installer | Pixel-identical | ❌ |
| `wkhtmltoimage` | ~50 MB external binary | Good | ❌ upstream archived |
| Render the PDF, convert to PNG | +30 MB (PyMuPDF) | **Looks like the PDF** | ❌ reproduces the thing being complained about |

Pillow 12.3.0 is already installed and already inside `arichds.exe` — it arrives transitively
through `fpdf2`, with FreeType compiled in, so it can set text in a real TrueType face. Adding
the third renderer therefore costs a promotion of Pillow from a transitive dependency to a
declared one and nothing else. `pyproject.toml` states the standing constraint the browser
option would break: *"Both pure Python (no Cairo/Pango/native ext)"*.

The last row matters most. Converting our own PDF to an image would produce an image of the
document the customer already rejected. It is the cheapest option and the only one that cannot
possibly work.

## The decision

The Billing capture image is produced by a **third renderer in `capture/`, drawing with
Pillow, fed by the same `_render_shared` section model that already feeds `pdf.py` and
`xlsx.py`**. ADR 0010 established that pattern deliberately — two renderers over one shared
section module — and this is the third instance of it, not a new mechanism.

It is written by the existing eager path (`acquisition/billing.py` → `_capture_new_closed_periods`)
under its own licence flag, alongside `auto_capture` (PDF) and `billing_excel_export` (xlsx).
That path already runs on the Scheduler thread with no browser and no UI, which is precisely
the property the customer asked for and which the product has had since M6.

## Consequences

- **The image will not survive a pixel-diff against a screenshot.** Fonts will differ slightly,
  card shadows and the antd focus ring will be absent, and the browser's own scrollbar will not
  appear. This is the accepted cost. If a customer ever requires byte-identity with Chrome, the
  answer is a 250 MB installer, and that is a commercial decision, not a technical one.
- **The image is not truncated the way the screen is.** A real screenshot of the Billing table
  cuts off mid-table — the page scrolls horizontally across a 43-column span (ADR 0009). The
  drawn image has no viewport, so it carries every column. It is therefore *more* useful as
  evidence than the screenshot the request asked for.
- **`--no-browser` stays true of this product.** Nothing in ARICHDS launches, bundles, or
  supervises a browser process on a customer machine.
