# 03: Files reach the team's server over HTTPS

**What to build:** The first real transport, and the first end-to-end demo: an administrator
saves the HTTPS tab with the team's server URL and a token, presses **Test connection** and reads
the server's HTTP status back, presses **Upload now**, and the export files and capture documents
appear under the remote root on the server with the manifest beside them. The three file endpoints
are published on the in-app **API** page next to the push contract, marked **Files (optional)**,
so the receiving team can build them from one document. No new dependency: the standard-library
client the Central Push already uses, with the split connect/read timeouts it already has.
Decision record: ADR 0025 (decision 1, HTTPS); spec: `.scratch/file-upload/spec.md` → HTTPS
contract.

**Blocked by:** 02 (the cycle and the transport seam)

**Status:** ready-for-agent

- [ ] **Prefactor first, in its own commit**: the split-timeout opener the Central Push client
      owns moves to a neutral module both the push client and this transport import; the push
      client's tests stay green unchanged
- [ ] The HTTPS transport implements the ticket 02 seam over `urllib` only (no `httpx`/`requests`
      in the product): `GET {url}/v1/files/manifest` (404 = no manifest), `PUT
      {url}/v1/files/{relative path}` with the file body and its sha256 in a header (any 2xx =
      stored), `PUT {url}/v1/files/manifest`. Every request carries `Authorization: Bearer
      <token>` — the HTTPS tab's own token field, which may be the Push Token or another
- [ ] A non-2xx, a timeout and an unreachable host each surface as the transport's own error
      class carrying only the failure's class name — never `TypeError`/`AttributeError`, never the
      URL or the token — and the `https://` branch is exercised by a test, not only `http://`
      (memory: *a transport branch no test reaches ships broken*)
- [ ] **Test connection** on the HTTPS tab: an admin-only endpoint gated by the feature key that
      performs the manifest `GET` with the short connect timeout the Database Destination's test
      uses and reports the HTTP status and whether a manifest exists; refused checks name which
      one failed (unreachable / timed out / unauthorized / other)
- [ ] The three endpoints are published on the API page from the same models that build the
      requests, as a **Files (optional)** section — `contract_version` stays 1, and the push
      payloads are untouched (a test asserts the existing contract render is unchanged apart
      from the new section)
- [ ] The fake receiver gains the three file endpoints (verifying the Bearer token, storing
      bodies and the manifest in memory) on its ephemeral port; transport tests assert the file
      arrived byte-equal, the manifest round-trips, and a wrong token is refused as unauthorized
- [ ] Web: the HTTPS tab's **Test connection** button and its result sentence; the how-to names
      the three endpoints and points at the API page; English only
- [ ] `CLAUDE.md`'s ADR 0025 digest records what landed; `installer/README.md` gains a
      troubleshooting row for an HTTPS upload that is refused
- [ ] Every test above is mutation-probed: reverting the behaviour it names turns it red
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `pytest -n auto` in `app/`;
      `pnpm lint` + `pnpm build` in `web/`
