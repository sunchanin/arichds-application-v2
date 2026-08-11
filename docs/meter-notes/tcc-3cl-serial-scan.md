# SMART TCC ST-3CL — first read off real hardware, 2026-08-11

**This is the first time any of the five SMART TCC models has been read from a
real meter.** The site's TCP endpoint (`203.170.148.103:4059`) has never
answered; this unit was reached over **serial** on the customer's machine with
`app/scripts/probe_tcc.py`. The driver under test is the shipped one
(`SmartTccDriver`), not a reimplementation, so what passed here is what the
product does.

The older TCC record in [`tcc-obis-scan.md`](tcc-obis-scan.md) came from v1 and
a different unit; where the two disagree, this file describes the unit in
service.

| | |
|---|---|
| Meter serial (`0.0.96.1.0.255`) | **`002607000049`** |
| Transport | serial, **COM3**, **9600 8N1** |
| Client / server | client 1, physical 127, logical 127 |
| Auth / security | HighGMAC + AuthenticationEncryption, Suite 0 |
| Association | **opens and authenticates** with the driver's own key material |

## What the driver got right, confirmed against hardware

Everything the connection profile declares matched, and the association opened
on the first candidate line setting. Before the probe ran, the same profile had
already been cross-checked against the customer's Gurux Director export
(`tcc.gxc`) and association view (`test 3CL.xml`): **the block cipher key and
the authentication key on the device are the values the driver already
carries**, so no per-site key is owed.

**Load profile `1.0.99.1.0.255` — read successfully.**

| | |
|---|---|
| Capture period | **900 s** |
| Entries in use | 83 |
| Live capture columns | **35** |
| Rows returned over a 6 h window | 24 |

Ten of the eleven columns the driver maps came back with values, and the values
are plausible: phase voltages 216–234 V across the window, currents and all
four energy columns at 0 (the meter is on an unloaded test bench, which the
zero currents independently corroborate).

## Two gaps this read exposed

### 1. `avg_geo_pf` is captured but never stored

`1.0.13.27.0.255` **is** in the live capture list, and the driver maps it to
`avg_geo_pf` — but it comes back `None` on every row, because the scaler cannot
be resolved for it. **This is the same failure the CEWE Prometer 100 shows on
the same field**, so it is a pattern across brands rather than a TCC quirk. It
is the one declared load-profile column this model does not deliver.

### 2. The meter has **nine** tariff slots; our schema has five

Every billing quantity is captured at `E=0` plus `E=1..8`. `billing_readings`
models `total` + `rate_a..rate_d` — five slots — so **E=5, 6, 7 and 8 are
dropped structurally**, 68 columns in total.

That is not a defect on its own: a meter offering eight tariffs does not mean
the customer bills on eight. But it is an **open question for the owner**, and
it is the kind that is expensive to answer late, because adding tariff slots
means a schema migration. It has not been decided.

### Full accounting of the billing capture list

The billing profile serves **148** capture columns. The driver maps **60**:

| Dropped | Count | Why |
|---|---|---|
| Tariffs `E=5..8` across every group | 68 | no schema slot (see above) |
| `C=2`/`C=4` cumulative demand (`D=2`), `E<=4` | 10 | export-side cumulative demand is not in the field set |
| `C=2`/`C=4` demand capture time (`D=6`, attr 5), `E<=4` | 10 | export-side Demand Time is not in the field set |
| Billing counters (`D=1`) | 2 | not measurements |
| Clock + the profile's own self-reference | 2 | structural |

Note the profile lists itself as a capture object with **`attr=-1`**
(`1.0.98.1.0.255`), as the load profile does (`1.0.99.1.0.255`). Position
mapping keys on `(OBIS, attribute)` and simply never matches it, so it costs
nothing — but a reader comparing column counts by hand should expect it.

## What this read could NOT establish

**`entries_in_use: 0` on the billing profile — the buffer is empty.** No billing
period has ever closed on this unit, so `read_billing()` correctly returned zero
rows. The billing path is therefore **structurally** verified on TCC (the
profile opens, the capture list parses, the 60 mapped columns all exist) and
**not** data-verified. Nothing here says whether the values would be right.

## One unexplained result, recorded rather than smoothed over

The first probe run, at **9600 8N1 — the same settings that later worked** —
failed with `TimeoutException` after the driver's full 90 s wait. The second run
opened the association at that same setting within the sweep's 4 s window.

The line settings were therefore never the problem, and the first failure has no
confirmed cause. The most likely one is another program holding COM3 (Gurux
Director was in use on that machine), since a held port produces silence
indistinguishable from a wrong baud. **If a TCC association fails once, retry
before changing anything.**
