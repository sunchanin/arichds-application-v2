# 07: An administrator configures the Central Push on the API page

**What to build:** An **API** page under Data-out, where an administrator enters the team's server
URL and pastes a Push Token, and where anyone building the receiving server can read the exact
contract the machine will push. Saving a token checks it on the spot, and refuses one issued for a
different machine. Nothing is sent yet — ticket 08 does that — but the page is complete: a
configured machine shows that it has a URL and a token, and the contract is published. Decision
record: ADR 0024; spec: `.scratch/central-push/spec.md` (Contract version 1).

**Blocked by:** 03 (the Push Token verifier)

**Status:** ready-for-agent

- [ ] Settings hold the server URL and the Push Token. The token is **write-only**: no endpoint
      returns it, the configuration response reports only whether one is set, and the credential
      redaction filter covers it — a test captures the log output and finds no token
- [ ] Admin-only endpoints: read and update the configuration, read the last cycle's status, and
      read the published contract. No licence feature key gates them
- [ ] **Saving a token verifies it** with ticket 03's verifier, and requires its Machine ID to
      equal this machine's own. A token for another machine, a tampered token, a token signed by
      another key and an Activation Code are each refused, with a message naming the failed check
- [ ] An empty URL means the push is disabled
- [ ] The payload definitions for contract version 1 exist as models: the holdings response, the
      push envelope, and the four item kinds — `meters`, `billing`, `energy_summary`,
      `load_profile` — with the fields the spec lists
- [ ] **The contract is rendered from those models**: it lists every field the models declare, so
      a field added to a model appears in the contract with no other change
- [ ] The contract also states the natural key of each kind, units (always kWh, kvarh, V, A),
      that instants carry a UTC offset and `local_date` is a plain date, the meaning of bit 0 of
      `interval_status_flag`, how holdings are answered, and that rows older than the machine's
      90-day window are never sent again
- [ ] Before ticket 08 lands, the status endpoint reports that no cycle has run
- [ ] Web: an **API** page under Data-out, admin only — a configuration form with a write-only
      token field and a "token set" indicator, a status card, and a read-only contract view.
      English only
- [ ] `test_nav_feature_contract.py` stays green with the new nav entry
- [ ] Every test above is mutation-probed: reverting the behaviour it names turns it red
- [ ] `CLAUDE.md`'s digest for ADR 0024 records what landed
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `pytest -n auto` in `app/`;
      `pnpm lint` + `pnpm build` in `web/`
