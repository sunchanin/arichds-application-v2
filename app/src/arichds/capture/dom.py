"""The DOM/JS contract between ``web/`` and ``app/`` (ADR 0017, issue #38).

The headless-screenshot renderer (:mod:`arichds.capture.screenshot`) drives
our own SPA over CDP and depends on strings no type checker ties together:
the ``localStorage`` key the session lives under, the name of the global the
page reads its capture request from, the two request fields the Capture
Style added (ADR 0028), and the CSS selectors that locate the rendered rows
of the Billing table and of the Classic page. **One named place for all of
them, and nothing else** — the renderer imports from here and hardcodes
none of them.

Kept deliberately free of any DB/auth/rendering logic (that lives in
:mod:`arichds.capture.screenshot`) so this module can be read end to end in
under a minute by whoever next has to explain why a capture broke after a
``web/`` change.
"""

from __future__ import annotations

import json

#: ``web/src/auth.ts`` — ``SESSION_KEY``, the ``localStorage`` key the
#: session lives under. The seed script writes a session here before
#: navigation so the SPA boots signed in.
SESSION_STORAGE_KEY = "arichds.session"

#: ``web/src/capture.ts`` — the ``window`` global a capture request is read
#: from once, at module load. Absent or malformed is treated as "no request"
#: (a broken global must never break the page for a human).
CAPTURE_REQUEST_GLOBAL = "__ARICHDS_CAPTURE__"

#: ``web/src/capture.ts`` — the request field naming the Capture Style
#: (ADR 0028): ``"classic"`` makes ``App.tsx`` render the Classic page instead
#: of the Billing page; absent or anything else is Standard, the contract's
#: own rule that a malformed global never breaks the page for a human.
CAPTURE_STYLE_FIELD = "style"

#: ``web/src/capture.ts`` — the request field carrying the anchor period's
#: ``BillingReading.id``, which the Classic page passes to
#: ``GET /api/billing/capture-classic/{device_id}?reading_id=`` so it draws
#: exactly the window ``_png_source_rows`` selected — a same-second pair's
#: older member (ADR 0029) cannot be named by ``endIso`` alone.
CAPTURE_ANCHOR_FIELD = "anchorId"

#: ``web/src/components/AppShell.tsx`` renders its root as an AntD
#: ``<Layout>`` — used only to tell "the SPA never mounted at all" apart from
#: "the SPA mounted but the Billing table never matched" in a timeout's
#: message. The row-id comparison below stays the only *correctness* gate
#: (decision 6, issue #38) — this selector never gates anything by itself.
APP_SHELL_SELECTOR = ".ant-layout"

#: ``@rc-component/table`` (antd 6's table) — every rendered body row carries
#: this selector. Verified against the installed package at
#: ``web/node_modules/.pnpm/@rc-component+table@*/node_modules/@rc-component/table/es/Body/BodyRow.js``
#: (sets ``data-row-key``) and ``Body/index.js`` (the ``-tbody`` class); the
#: measure row (``Body/MeasureRow.js``) carries no ``data-row-key``, so this
#: selector already excludes it.
TABLE_BODY_ROW_SELECTOR = ".ant-table-tbody tr[data-row-key]"

#: The attribute each body row carries its row key in. ``Billing.tsx`` sets
#: ``rowKey={(row) => row.id}``, so this attribute's value is the row's own
#: ``BillingReading.id`` as a string.
ROW_KEY_ATTRIBUTE = "data-row-key"

#: ``web/src/pages/ClassicCapture.tsx`` — the Classic page renders no AntD
#: table (ADR 0028), so its Data Table rows are found under the page's own
#: root class, each ``<tr>`` carrying :data:`ROW_KEY_ATTRIBUTE` exactly as
#: the Billing page's rows do.
CLASSIC_TABLE_BODY_ROW_SELECTOR = ".classic-capture tbody tr[data-row-key]"


def poll_script(style: str = "standard") -> str:
    """The JS expression polled while waiting for the Billing table to
    render (step 5, issue #38) — or, with *style* ``"classic"``, the Classic
    page's Data Table (ADR 0028).

    Returns an object ``{mounted, ids}`` in one round trip: ``mounted`` is
    whether :data:`APP_SHELL_SELECTOR` exists at all (diagnostic only, and
    false by design on the Classic page, which has no shell), and ``ids`` is
    the list of :data:`ROW_KEY_ATTRIBUTE` values off
    :data:`TABLE_BODY_ROW_SELECTOR` (:data:`CLASSIC_TABLE_BODY_ROW_SELECTOR`
    for Classic), in DOM order, **de-duplicated by id**
    (Findings: ``scroll={{ x }}`` splitting header/body into separate tables
    "should not duplicate body rows, but confirm rather than assume" — this
    de-duplicates defensively so a duplicate, if it exists, never inflates
    the comparison instead of just failing it).
    """
    row_selector = CLASSIC_TABLE_BODY_ROW_SELECTOR if style == "classic" else TABLE_BODY_ROW_SELECTOR
    return (
        "(() => ({"
        f"mounted: !!document.querySelector({json.dumps(APP_SHELL_SELECTOR)}), "
        "ids: (() => { "
        "const seen = new Set(); const out = []; "
        f"document.querySelectorAll({json.dumps(row_selector)}).forEach((el) => {{ "
        f"const id = el.getAttribute({json.dumps(ROW_KEY_ATTRIBUTE)}); "
        "if (!seen.has(id)) { seen.add(id); out.push(id); } "
        "}); "
        "return out; "
        "})()"
        "}))()"
    )


def build_seed_script(session: dict[str, object], capture_request: dict[str, object]) -> str:
    """The script registered via ``Page.addScriptToEvaluateOnNewDocument``
    (step 4, issue #38) — seeds *both* the session and the capture request
    before the SPA's first render.

    Args:
        session: The ``web/src/auth.ts`` ``Session`` shape — ``id``,
            ``token``, ``username``, ``role``.
        capture_request: The ``web/src/capture.ts`` ``CaptureRequest``
            shape — ``deviceId``, ``meterSerial``, ``endIso``, ``pageSize``,
            :data:`CAPTURE_STYLE_FIELD` and :data:`CAPTURE_ANCHOR_FIELD`.

    Returns:
        A self-contained JS statement. ``session`` is stored as a JSON
        *string* (``localStorage.setItem`` always stores strings — matching
        ``auth.ts``'s own ``JSON.parse(raw)`` on read), so it is
        double-encoded: the outer :func:`json.dumps` produces a JS string
        literal, the inner one produces the JSON text that literal holds.
    """
    session_literal = json.dumps(json.dumps(session))
    request_literal = json.dumps(capture_request)
    return (
        f"window.localStorage.setItem({json.dumps(SESSION_STORAGE_KEY)}, {session_literal});"
        f"window.{CAPTURE_REQUEST_GLOBAL} = {request_literal};"
    )


def ids_match(expected_ids: list[str], observed_ids: list[str]) -> bool:
    """Whether the rendered rows are exactly *expected_ids*, in order
    (decision 6, issue #38) — same length, same values, same order, checked
    in one comparison rather than three.

    A pure function so it is unit-testable with no browser (step 5).
    """
    return list(expected_ids) == list(observed_ids)
