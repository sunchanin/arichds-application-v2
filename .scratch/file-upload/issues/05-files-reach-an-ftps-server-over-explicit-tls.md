# 05: Files reach an FTPS server over explicit TLS

**What to build:** An administrator saves the FTPS tab with the server, port (default 21), a
username and a password; **Test connection** reports the certificate subject the server
presented; **Upload now** fills the remote root over explicit TLS. "Encrypted" means encrypted:
the control channel upgrades with `AUTH TLS`, the data channel is protected, and the certificate
is verified against the system trust store with a hostname check — a self-signed certificate is a
failure, not a prompt. Standard library only. The owner kept FTPS against the grill's
recommendation (ADR 0025 → Consequences: revisit if no site configures it within a year), so the
how-to has to be good enough that nobody calls the vendor. Decision record: ADR 0025 (decision 1,
FTPS); spec: `.scratch/file-upload/spec.md` → FTPS specifics.

**Blocked by:** 02 (the cycle and the transport seam)

**Status:** ready-for-agent

- [ ] The FTPS transport implements the ticket 02 seam over the standard library's `FTP_TLS`:
      explicit `AUTH TLS` on the configured port, passive mode, `PROT P`, a default SSL context
      (system trust store, hostname verification on). Implicit FTPS is not offered and port 990 is
      not special-cased
- [ ] A self-signed or otherwise untrusted certificate, a refused connection, a timeout, bad
      credentials and a missing remote directory each surface as the transport's own error class
      carrying only the failure's class name — never the host or the password
- [ ] Remote directories are created on demand (the `export/` and `captures/<Meter Serial>/`
      layers), and an existing one is not an error
- [ ] **Test connection** on the FTPS tab logs in, lists the remote root, and reports the
      certificate subject and whether a manifest exists, with the short connect timeout the
      Database Destination's test uses
- [ ] Transport tests against a `pyftpdlib` TLS server **in-process** on an ephemeral port
      (`pyftpdlib` is a dev-only dependency): a self-signed certificate is **refused**; the same
      server trusted through the test's own SSL context succeeds with the file byte-equal and the
      manifest round-tripping; a wrong password surfaces as the transport error class. The test
      must not touch the machine's real trust store
- [ ] Web: the FTPS tab's **Test connection** and its result sentence; the how-to names what to
      create on the server (user, folder, port 21, a certificate the machine's Windows trust store
      accepts), what the machine will create, and what is not supported (plain FTP, implicit
      FTPS, self-signed certificates, deleting); English only
- [ ] `CLAUDE.md`'s ADR 0025 digest records what landed; `installer/README.md` gains a
      troubleshooting row for a certificate the trust store rejects
- [ ] Every test above is mutation-probed: reverting the behaviour it names turns it red
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `pytest -n auto` in `app/`;
      `pnpm lint` + `pnpm build` in `web/`
