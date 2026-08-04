# License activation applies live — no process restart

Status: accepted (2026-08-03, M1 grilling)

v1 (cewe) explicitly required a process restart for invalid→valid license recovery — a
consequence of enforcement state being loaded once at startup. v2 deliberately reverses this:
pasting a valid Activation Code on the first-run page takes effect **immediately** — the
enforcement layer re-evaluates in-process, polling starts, and the web UI continues without a
service restart.

Why: activation moved from the installer (v1) to a web page (v2). A web flow that ends with
"now wait while the service restarts itself" is fragile (the process would have to orchestrate
its own NSSM restart) and confusing. Designing enforcement as re-evaluatable state from day
one is cheap; retrofitting it later (v1's position) is what made v1 give up and require the
restart.

Consequence: any M1+ code holding license-derived state (enforcement middleware, feature set,
meter quota) must read it through the re-evaluatable license service — never cache it at
import/startup time. Anyone porting v1 license code must not carry over its load-once pattern.
