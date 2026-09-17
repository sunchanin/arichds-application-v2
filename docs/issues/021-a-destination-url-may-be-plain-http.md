# A Destination URL is accepted with `http://`, so a token and every payload can cross the wire in clear text

**Type**: AFK · **Found**: file-upload ticket 03 review, 2026-09-17 (reviewer nit 7, deliberately left
out of that ticket because fixing one destination alone would make the three disagree) · **Blocks**:
nothing shipped; both pages *promise* an encrypted transfer their save endpoint does not enforce

## The problem

Two Data-out Destinations take a URL and a bearer token and neither checks the scheme at save time:

- `api/central_push.py` — `CentralPushIn.url`, documented as "Not validated at save time — the same
  convention `db_dest_host` uses". The Push Token (a signed JWT) is sent as `Authorization: Bearer`
  on every request.
- `api/file_upload.py` — the HTTPS tab's URL (`PUT .../https`, `fileupload_https_url`). The tab is
  labelled **HTTPS**, its how-to says the certificate is checked against the system trust store
  (ADR 0025), and `HttpsTransport` sends the token plus every export file and capture document.

`HttpsTransport` and the push client are deliberately scheme-blind: every test in the repo speaks
`http://` to an in-process receiver on `127.0.0.1:0`, and the one TLS test asserts that a self-signed
certificate is *refused*. So an operator who types `http://files.example.com/` gets a working upload
with no warning, and the "encrypted" promise on the page is false for that site.

The Database Destination is a different case: PyMySQL's TLS is a property of the server's `my.cnf`
and the account's `REQUIRE SSL`, not of a URL, so `db_dest_host` has no scheme to check.

## What to do

Decide once, for both URL-taking destinations:

1. **Refuse `http://` at save time** (recommended): the `PUT` handlers return 422 naming the field
   when the scheme is not `https`, the pages' how-tos say so, and the two `CentralPushIn.url` /
   HTTPS-tab docstrings lose their "not validated" sentence. The transports stay scheme-blind so the
   fake-receiver tests keep speaking `http://` — the tests that go through the *API* need one
   allowance: an environment/setting override for tests only (the way `ARICHDS_POLL_ENABLED` is), or
   the test suite pointing the API at an `https://` URL whose TLS test server the suite already knows
   how to build (`test_fileupload_https_transport.py::TestHttpsBranchIsExercised` generates one).
2. **Or** keep accepting it and make the page say plainly that `http://` sends the token and the
   files in clear text — a warning `Alert` when the saved URL is not `https://`.

Either way the two destinations must agree, and `SPEC.md` §3.8's wording ("encrypted", ADR 0016's
"plain FTP is never acceptable") should be read as favouring option 1.

## Evidence

- `.claude/run-logs/issue-file-upload-03.md` — the review that parked it.
- `app/src/arichds/api/central_push.py` (`CentralPushIn.url` docstring), `app/src/arichds/api/file_upload.py`
  (the HTTPS `PUT` handler's URL validation — non-empty only).
