"""The ``[meter]``/``[serial]``/``[date]`` export-filename tokens — the one
place that knows what they mean (F4, ``export/format.py``; reviewer finding,
File Upload Destination ticket 02 round 1).

Two things need this knowledge for two different reasons: ``export/format.py``
renders a **literal** filename to write a file under, and
``fileupload/cycle.py`` needs to recognise **which already-written files**
belong to a given device without predicting a name and hoping it still
exists — "the file on disk is the contract" (ADR 0025, ticket 02). Before
this module existed, ``fileupload/cycle.py`` carried its own hand-copied
substitution, byte-for-byte identical to ``export/format.py::render_filename``
by coincidence and pinned together by nothing — a future change to the
product's naming (a new token, a changed substitution) would silently make
the cycle look for names that no longer exist, and a mutation to
``render_filename`` alone left every File Upload Destination cycle test
green.

This module lives at the top of the package, exactly like
:mod:`arichds.interval_status` and for the identical reason: **the consumer
must not import** ``export/`` (ADR 0021's reasoning for
:mod:`arichds.dataout`, extended to :mod:`arichds.fileupload`), so the one
piece of knowledge both sides need has to live somewhere neither owns.
``export/format.py::render_filename`` **delegates** to
:func:`render_filename_tokens` rather than reimplementing it, so the
correspondence between "what gets written" and "what the token substitution
means" is a fact enforced by the import graph, not a comment repeated in two
files.
"""

from __future__ import annotations

import re
from datetime import date

#: The two tokens that mean "this device's Meter Serial" — kept as a tuple
#: rather than a single token because v1 parity already treats the two names
#: as synonyms (``export/format.py``'s own F4 rule).
_METER_TOKENS: tuple[str, ...] = ("[meter]", "[serial]")

#: The one token that means "today, rendered ISO-8601" when writing, and
#: "any day, in that exact shape" when matching an already-written file.
_DATE_TOKEN = "[date]"

#: ``date.today().isoformat()``'s own shape (``YYYY-MM-DD``) — the only shape
#: this token has ever produced, so a match against it is exact rather than a
#: bare wildcard that would also swallow an unrelated suffix.
_DATE_PATTERN = r"\d{4}-\d{2}-\d{2}"


def render_filename_tokens(template: str, meter_token: str) -> str:
    """Substitute every token in *template* with a literal value.

    Args:
        template: A filename template, e.g. ``"[meter].csv"``.
        meter_token: The sanitized meter serial — substituted for both
            ``[meter]`` and ``[serial]``.

    Returns:
        The rendered filename with every token substituted, ``[date]``
        becoming today's date.
    """
    filename = template
    for token in _METER_TOKENS:
        filename = filename.replace(token, meter_token)
    return filename.replace(_DATE_TOKEN, date.today().isoformat())


def export_filename_pattern(template: str, meter_token: str) -> re.Pattern[str]:
    """A regex matching any filename *template* could have produced for
    *meter_token*, on **any** day this machine has ever run — the inverse of
    :func:`render_filename_tokens`, used to recognise an already-written file
    rather than to write a new one.

    Args:
        template: The same filename template :func:`render_filename_tokens`
            takes.
        meter_token: The device's Meter Serial, matched literally (escaped
            before compiling, so a serial containing a regex metacharacter
            cannot widen the match).

    Returns:
        A compiled, fully-anchored pattern.
    """
    pattern = re.escape(template)
    for token in _METER_TOKENS:
        pattern = pattern.replace(re.escape(token), re.escape(meter_token))
    pattern = pattern.replace(re.escape(_DATE_TOKEN), _DATE_PATTERN)
    return re.compile(f"^{pattern}$")


__all__ = ["export_filename_pattern", "render_filename_tokens"]
