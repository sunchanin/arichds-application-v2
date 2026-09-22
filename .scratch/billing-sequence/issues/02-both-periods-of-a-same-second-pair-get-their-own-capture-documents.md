# 02: Both periods of a same-second pair get their own capture documents

**What to build:** When a closed period shares its bill date with another, each gets its own PDF,
xlsx and PNG. The second period's documents take the same stem with `_2` appended
(`2026-09-19_085950_2.pdf`; a third would be `_3`); a period alone on its bill date keeps
today's unsuffixed name, so **no file already handed over is renamed**. All three write paths
agree on the name — the automatic capture of a new closed period, the Capture image button and the
render-on-miss download — and the PNG's ten-period window counts a pair as two of its ten, ordered
oldest first as the page now is. The FTP upload picks the suffixed documents up like any other.
Decision record: ADR 0029 (filename), ADR 0015 (one stem, three formats — still true); spec:
`.scratch/billing-sequence/spec.md`; glossary: CONTEXT.md → *Capture*, *Billing Sequence*.

**Blocked by:** 01 (ARICHDS holds every closed period the meter holds, oldest first)

**Status:** ready-for-agent

- [ ] The one stem function takes the sequence: `0` → byte-for-byte today's path (an existing
      test's expected value is unchanged); `1` → `_2`; `2` → `_3`; all three formats share the
      suffixed stem (`test_capture_paths.py`, `test_capture_service.py`)
- [ ] The eager write after a whole-buffer read writes documents for **both** members of a pair
      (`test_billing_eager_capture.py` shape), and the Billing page's *Captured* column is stamped
      on each period once its own file exists
- [ ] The Capture image button and the render-on-miss download for the `sequence = 1` period
      resolve the suffixed path — a download of the pair's second period never serves or writes
      the first period's file (`test_api_billing_captures.py`)
- [ ] The PNG window: for an anchor whose ten-period window contains a pair, the selected rows
      include both, ordered `bill_date ASC, sequence ASC`, and the renderer's expected row-id list
      is built in that same order (fake CDP transport, `test_capture_screenshot*.py`)
- [ ] FTP: a suffixed document under `captures/<serial>/` is listed and uploaded with no
      configuration change (`test_fileupload_cycle.py` shape) — proven, not assumed
- [ ] The opt-in real-Edge test (`ARICHDS_TEST_EDGE=1`) run by hand once with a pair in the
      seeded rows; its output line in the evidence
- [ ] Docs in the same change: CONTEXT.md *Capture* names the suffix rule in one sentence;
      CLAUDE.md's ADR 0015 and 0029 digests mention it
- [ ] Gate: `ruff format --check`, `ruff check`, `pytest -n auto` (app)
