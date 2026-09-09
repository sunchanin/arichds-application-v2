# 02: A manual billing read says how many captures it wrote

**What to build:** An operator presses Read now on the Billing page and the confirmation
tells them how many captures were written, alongside how many periods were stored.

Today it reports only the periods. The two are not the same number: when the capture folder
has not been set, captures are switched off, so periods are stored and **no documents are
produced at all** — and the current message reads as though they were. An operator who
hands those documents to a customer finds out at the wrong moment.

Source: `../spec.md`. Glossary term **Capture** is in `CONTEXT.md`; the capture folder being
an operator setting is ADR 0010.

**Blocked by:** None (can start immediately).

> Not a blocker, but worth knowing: ticket 01 edits the same billing API module and the same
> Billing page, in different places. If both are run by agents, running 01 first avoids a
> merge conflict. Neither gates the other.

**Status:** ready-for-agent

- [ ] The billing read path **reports how many captures it wrote**, carried on the same
      result the stored count already travels on
- [ ] The manual billing read response exposes that count
- [ ] The confirmation message on the Billing page **states both** the periods stored and
      the captures written
- [ ] When the **capture folder is unset**, the reported capture count is **zero** while the
      stored count is unchanged
- [ ] The count comes from the **read path itself**, never inferred in the browser from the
      capture-folder setting — that setting is **not loaded for non-admin roles**, so an
      inferred count would be wrong for them
- [ ] The count is exercised through the **real store path**. The fake-meter fixture is
      autouse; a test that takes the number from a fake would stay green while proving
      nothing
- [ ] Tests sit at the **existing HTTP seam** through the shared test-client fixtures — no
      new seam
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `python -m pytest -n auto` in
      `app/`; `pnpm lint` + `pnpm build` in `web/`. The **full** suite, never a subset
- [ ] **Output Parity vs v1**: not applicable — v1 has no equivalent message. Say so
- [ ] **Real-meter read**: not applicable — the read path is exercised through the existing
      fixtures, and nothing here changes what is asked of a meter. Say so
