# The capture image is a headless screenshot of our own page

**Reverses ADR 0014.** That ADR chose Pillow over a headless browser on one load-bearing
premise: *"When nobody is looking at the page there is no screen to photograph — no browser, no
viewport, no session, no logged-in user."* Each of those four is false, and a working prototype
proved it on this machine on 2026-08-22. The Billing capture image is now taken by driving the
**already-installed** Microsoft Edge over the Chrome DevTools Protocol against our own SPA, with
nobody logged in and no window on screen.

## What the prototype demonstrated

It signed itself in, walked to the Billing page, cycled the device filter one meter at a time,
and wrote one PNG per meter — all headless, all unattended:

```
  menu: ['Devices', 'Load Profile', 'Records', 'Billing', …]
  Phase 2 (SS18197374)             -> 1960x1080   56 KB  Phase_2_SS18197374.png
  Prometer100_4059 (WP079074)      -> 1960x1080   54 KB  Prometer100_4059_WP079074.png
  saral (SS21996979)               -> 1960x1080   54 KB  saral_SS21996979.png
```

Point by point against 0014's premise:

| 0014 said | What is actually true |
|---|---|
| no browser | Edge 151.0.4129.101 ships with Windows, at a fixed path. Nothing to bundle. |
| no viewport | `Emulation.setDeviceMetricsOverride` sets one. `--headless=new` needs no desktop. |
| no session | `Page.addScriptToEvaluateOnNewDocument` seeds `localStorage` **before** the SPA boots. |
| no logged-in user | The renderer mints its own short-lived token through the same code path `auth/service.py` login uses, and revokes it in a `finally`. No stored credential, no standing account. |

## Why the cost argument also collapsed

0014 priced the browser option at *"35 MB → ~250 MB installer"*. That was the cost of
**bundling** Chromium via Playwright. Driving the browser the operating system already installed
costs **0 MB**, and the WebSocket client needed to speak CDP is `websockets 17.0.1`, already
present because `uvicorn[standard]` pulls it. The comparison table in 0014 never considered this
row, and it dominates every row that is in it.

`pyproject.toml`'s *"pure Python, no native ext"* constraint is untouched — we add no dependency
at all. What does change is 0014's closing line, *"nothing in ARICHDS launches, bundles, or
supervises a browser process on a customer machine"*: we now **launch** one, briefly, per
capture. We still bundle and supervise none.

## The decision

The capture PNG is produced by loading `http://127.0.0.1:<port>/` in headless Edge and calling
`Page.captureScreenshot`. `capture/png.py` and its Pillow drawing code are retired.

Fidelity stops being an approximation and becomes an identity: the image **is** the product's
own rendering, so a re-theme, a column change or a new AntD version reaches the capture with no
renderer edit. 0014 accepted "fonts will differ slightly, card shadows and the focus ring will be
absent" as a permanent cost; that cost is now zero.

## What this costs instead

- **Edge cannot run as LocalSystem — but the service still can.** `msedge.exe` exits **1002**
  immediately under `nt authority\system`, for any argument including `--version`, and runs
  normally under `nt authority\local service`. Session 0 is *not* the obstacle; the SYSTEM
  account is.

  **Correction, 2026-08-22 (same day).** This bullet first read *"the service can no longer run as
  LocalSystem"* and called that the largest consequence of the ADR. That inference was wrong, and
  issue #38 shipped it: the service was switched to `NT AUTHORITY\LocalService`, and on the first
  real install the capture failed with a 422 because LocalService cannot write a `capture_dir`
  under `C:\Users\…`, which is where operators actually put it. The Load Profile CSV export
  directory has the same shape and would have failed the same way, silently.

  What is actually true is narrower: **only the `msedge.exe` launch must leave SYSTEM.** Edge never
  writes the capture — it renders and returns bytes over CDP, and the service writes the file. So
  the browser is started through a Windows scheduled task registered to
  `NT AUTHORITY\LOCAL SERVICE`, triggered by the service with `schtasks /run`, while the service
  itself stays `LocalSystem` and everything it already does — the Poller, the exports, the capture
  write — is untouched. The only NTFS grant needed is on `%ProgramData%\ARICHDS\tmp`, for Edge's
  own profile directory.

  Measured on this machine before adopting it, rather than reasoned about: a SYSTEM caller's
  `schtasks /run` returns 0 and Edge comes up owned by `LOCAL SERVICE` with a reachable CDP port;
  `Browser.close` takes all eleven of its processes down and returns the task to `Ready`;
  `schtasks /end` from SYSTEM does the same as a fallback; and a relaunch after either stop
  succeeds — which matters because `schtasks /run` refuses a task still marked `Running`, so a
  stop that left it stuck would have broken every capture after the first.
- **The image is truncated exactly as the screen is.** 0014 counted "carries every column" as an
  advantage over a screenshot. The owner reviewed the truncated prototype and chose the screen's
  own framing (*"คอลัมน์โดนตัดไม่เป็นไรเอาเท่าที่เห็นในหน้าจอ"*, 2026-08-22). The full 43-column
  span (ADR 0009) still reaches the customer through the `.xlsx`, which is unchanged.
- **A capture can now fail for browser reasons** — Edge missing, upgraded mid-write, or refusing
  to start. The eager path must treat that the way it already treats an `OSError`: log it, leave
  the billing row written, never block the Scheduler thread. A capture is a convenience; the
  reading is the product.
- **Driving our own UI means depending on its DOM.** The prototype already broke twice on this:
  AntD v6 removed `.ant-select-selector`, and a synthetic `MouseEvent` does not drive an AntD
  `Select` at all — only a real `Input.dispatchMouseEvent` does. Selectors used by the renderer
  are a coupling between `web/` and `app/` that no type checker will catch, so they belong in one
  named place with a test that fails when the page stops matching.

## What is unaffected

**ADR 0015 still holds in full** — three formats, one filename stem, and only the `.png` spanning
ten periods. That decision is about the shape of the deliverable, not about who draws it. The
renderer changes; the file name, the folder, and the ten-period span do not. ADR 0010's
`capture_dir` setting is likewise untouched.
