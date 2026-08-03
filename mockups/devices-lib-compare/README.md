# Devices page — library comparison mockup

Throwaway Vite app. v1's real Devices page — split tree + form layout, same
sections, same fields, same conditional logic — is rebuilt twice with two
candidate UI libraries, so the project owner can pick one for the v2 rewrite.
Not production code — nothing here is wired to a backend, and none of it
should be reused as-is.

**AntD was dropped as a mockup variant.** v1 (`cewe-fe/src/pages/Devices/index.tsx`)
*is* the AntD baseline already — it's real, running code, not something worth
re-mocking. The comparison is now: **v1 (reference) vs Mantine v9 vs shadcn/ui**.

## Run it

```
cd mockups/devices-lib-compare
pnpm install   # already done if you're reading this from a checked-out repo
pnpm dev
```

Routes:

- `/` — landing page, links to the two variants, with a note pointing at v1 as the AntD reference
- `/mantine` — @mantine/core v9 + @mantine/dates, teal-family primary
- `/shadcn` — Tailwind v4 + hand-built shadcn-style components (zinc palette) + the official shadcn Date Picker

`pnpm build` produces a production build in `dist/`; `pnpm preview` serves it.

## Layout parity with v1

This rebuild replicates v1's actual page **field-for-field and section-for-section**,
read directly from `cewe-fe/src/pages/Devices/index.tsx` (plus its supporting
`types/device.ts`, `types/meterCatalog.ts`, `utils/nextBillingCutDate.ts` — all
read-only reference, not modified):

- **Left panel — device tree** (not a data table; v1 has no table here): a
  header with `Devices (N)`, a licensed-meter-slot counter, a refresh-license
  icon button, a reconnect-all icon button, a search input, and a flat
  "type" filter (every model across every brand, independent of the
  Add/Edit form's brand→model cascade). Below it, devices grouped by
  **site name**, collapsible, each row showing a colored status dot + name
  + meter serial (if any) + `host:port` (TCP devices only — v1's tree data
  shape never carries serial-port info, so serial and Modbus devices show
  just their name).
- **Right panel — device control form**, always visible (there is no
  Add-Device modal in v1 — the same panel serves add *and* edit): a header
  (`Add New Device` / `Device Control` + live status tags + latency + last
  seen), then five bordered sections in v1's exact order:
  1. **Identity** — Device Name\*, Meter Serial (read-only), Site Code, Site
     Name\*, Customer Name, Meter Number, Meter Key (add-only, lease mode only)
  2. **Meter** — Brand\* → Model\* cascade, with not-yet-supported models
     shown disabled + "(coming soon)", matching v1's `driver_status` gating
  3. **Source** — DLMS / Modbus radio; Modbus reveals only a Slave Address
     field and hides the entire Connection section (v1's "Modbus is inert" rule)
  4. **Connection** (DLMS only) — Network (TCP) vs Serial radio with
     conditional IP+Port or SerialPort+Baud+DataBits+Parity+StopBits+FlowControl,
     a hint when the selected model advertises serial support, and a
     Password field that's hidden entirely for key-based (SMART TCC) models
  5. **Billing** — a computed "Next Cut Date" readout, a **Bill Start Date**
     date picker, and four Bill Day selects (Feb-28, Feb-29, 30-day, 31-day
     months) — this is the one real date control in v1, and both variants
     exercise their actual date-picker component here
  - Action row 1: Create Device (always visible, even with a device
    selected — that's v1's real behavior), Update Device, New Device (copy —
    clears selection but keeps the form as a template), Meter Setting (disabled)
  - Action row 2 (selected only): Disconnect (DLMS only, disabled once
    paused), Reconnect, Remove Device (confirm), Remove All Data (disabled)

Both variants share `src/mockData.ts` — 12 devices across 6 sites, a static
9-model catalog (mirroring `MeterCatalogModel`), a static license quota, and a
`resolveNextBillingCutDate` port of v1's own utility — so the comparison stays
apples-to-apples.

## `pnpm build` output

```
dist/index.html                                0.46 kB │ gzip:  0.30 kB
dist/assets/index-CDydLWhg.css                 0.23 kB │ gzip:  0.18 kB
dist/assets/ShadcnDevicesPage-*.css           21.86 kB │ gzip:  5.17 kB
dist/assets/MantineDevicesPage-*.css         257.96 kB │ gzip: 37.13 kB
dist/assets/mockData-*.js                     40.66 kB │ gzip: 14.65 kB
dist/assets/ShadcnDevicesPage-*.js           228.05 kB │ gzip: 67.94 kB
dist/assets/index-*.js                       232.32 kB │ gzip: 74.87 kB
dist/assets/MantineDevicesPage-*.js          312.81 kB │ gzip: 92.34 kB
✓ built in ~1s
```

(No AntD chunk — that variant and its `antd`/`@ant-design/icons`/`dayjs`
dependencies were fully removed from `package.json`.)

Each variant is `React.lazy`-loaded on its own route. `index-*.js` (React +
react-router-dom + the landing page) and `mockData-*.js` (the shared 12-device
catalog + domain helpers) are loaded once regardless of which variant you
visit, so they're excluded from the per-variant totals below.

| | JS (own chunk) | CSS (own chunk) | Variant total (gzip) |
|---|---|---|---|
| **Mantine v9** (`@mantine/core` + `dates` + `modals` + `notifications`) | 312.81 kB (92.34 kB gzip) | 257.96 kB (37.13 kB gzip) | **~129.5 kB gzip** |
| **shadcn/ui** (hand-built components + Radix primitives + `react-day-picker` + `sonner`) | 228.05 kB (67.94 kB gzip) | 21.86 kB (5.17 kB gzip) | **~73.1 kB gzip** |

Shared baseline (loaded once, every route): ~74.9 kB gzip JS (React 19 +
react-router-dom 7 + landing page) + ~14.7 kB gzip (the 12-device mock
catalog + domain helpers — bigger than in the first pass of this mockup
because it now carries the full v1-shaped catalog/quota/billing model, not
just `{id, brand, model, transport, status}`).

## Comparison table

| Criterion | AntD v6 = **cewe v1** (reference) | Mantine v9 | shadcn/ui + Tailwind v4 |
|---|---|---|---|
| **Data table** | No data table here either — v1's device list is a collapsible, site-grouped tree (`Spin` + plain buttons), not an AntD `Table`. AntD's `Table` component exists and is used for other v1 pages, just not this one. | Same tree, built from plain `<button>`s + Mantine layout primitives (`Group`/`Stack`) — no table component needed. | Same tree, plain `<button>`s + Tailwind flex utilities. (An earlier pass of this mockup used TanStack Table for a data-grid version of this page before re-reading v1 showed there's no table to replicate — dropped once real parity was required.) |
| **Date pickers** | `DatePicker` (antd, dayjs-based) for Bill Start Date. | **`DatePickerInput`** from `@mantine/dates` — `value`/`onChange` work in plain date **strings** (`YYYY-MM-DD`), not `Date` objects, even though `value` also accepts a `Date`; needs its own `@mantine/dates/styles.css` import alongside `@mantine/core/styles.css`; no dayjs/date-fns adapter setup required, dayjs is bundled internally. Confirmed against the installed `@mantine/dates@9.5.1` type declarations, not assumed. | shadcn ships an **official Date Picker** (`ui.shadcn.com/docs/components/base/date-picker`) — composed from `Popover` + `Calendar` (a `react-day-picker@10` wrapper) + a trigger `Button`, using `date-fns` for display formatting. react-day-picker v10 changed its `classNames` keys from earlier majors (now `day_button`, `month_caption`, `button_previous`/`button_next`, etc., driven by its `UI`/`DayFlag`/`SelectionState` enums) — the hand-built `calendar.tsx` here targets those current keys, read from the installed `react-day-picker@10.0.1` type declarations rather than an older recipe. |
| **Forms** | `Form` + `Form.useForm()` + `Form.useWatch` gives validation, cascading fields (brand→model, source→connection), and layout for free. | No form library bundled; this mockup hand-rolls the same validation v1 does (required fields, IP/serial-port pattern, baud-rate/slave-address bounds) via plain `useState` + an errors map. A real Mantine app would reach for `@mantine/form` or React Hook Form for this. | Same story — no form library shipped, same hand-rolled validation, same `useState` + errors map. Real shadcn usage typically pairs this with `react-hook-form` + `zod` (v1's own schema, in fact, is a zod schema already). |
| **Modals** | `Modal.confirm` for Remove Device; the page itself has no Add/Edit modal — it's a single always-visible form panel. | `@mantine/modals`' `modals.openConfirmModal` for Remove Device — first-party, separate package. | Radix `@radix-ui/react-dialog` hand-styled as the Remove-Device confirm — correct focus-trap/ESC/overlay behavior comes free from Radix; the visual chrome is our CSS. |
| **Notifications** | `message`/`notification` via `App.useApp()` (v5+ context pattern). | `@mantine/notifications` — `notifications.show(...)`, first-party, its own CSS import. | `sonner` — the toast library shadcn's own docs now recommend over the retired `Toast` primitive. |
| **Theming control** | `ConfigProvider` design tokens cascade to every component (color, radius, density algorithm, per-component overrides) — re-theming v1 without touching component code is realistic and is exactly what "re-theme AntD" would mean in practice. | `createTheme()` + CSS variables — `primaryColor`, `defaultRadius`, per-component `defaultProps`. Flexible, a little more manual than AntD's token cascade, still fully systematic. | Total control, zero framework: everything is CSS custom properties (`--primary`, `--radius`, …) consumed by Tailwind utilities we wrote by hand. No theme object to learn; also no free density/algorithm switch — every component's states are ours to define. |
| **Bundle (gzip, this page's own chunk)** | n/a — already shipping in v1 | ~129.5 kB | ~73.1 kB |
| **DX notes from this rebuild** | — | Rebuilding v1's tree+form layout was mostly translation, not invention: `Paper`+`Group`+`Stack` map cleanly onto v1's bordered sections and flex rows. The one real friction point was `DatePickerInput`'s string-typed `onChange` — easy to assume it hands back a `Date` and get a type error. Needing three separate Mantine packages (`core`, `dates`, `modals`, `notifications` — four, really) for one page is the recurring theme; each is well-documented and drops in cleanly, but it's more install/import ceremony than AntD's single package. | This was the long pole: nothing is free. The tree, the five form sections, the brand→model cascade, Radix `Select`/`RadioGroup`/`Dialog`/`Popover` wrappers, and the Calendar's `classNames` map all had to be written by hand, informed by the installed packages' own `.d.ts` files rather than guessed. That said, once the primitives existed, the actual page logic (validation, effects, patch-building) was near-identical code to the Mantine version — the divergence is almost entirely in the UI layer, which is the point of this comparison. Payoff: the smallest bundle by a wide margin, and a page that looks and feels exactly as dense/utilitarian as intended, not a reskinned default. |

## Assumptions made

Because this mockup has no backend, several v1 concepts that are normally
server-driven are static local data. Stated explicitly so nothing here reads
as an accidental gap:

- **Quota/license**: `QUOTA` in `mockData.ts` is a static `{ mode: "lease", maxMeters: null, used: 12 }` rather than a fetched `MeterQuota` — chosen specifically so the Meter Key field (add-only, lease-mode-only) has a reason to render, matching v1's real conditional.
- **Catalog**: `CATALOG_MODELS` mirrors v1's real `MeterCatalogModel` shape (`driver_status`, `supports_serial`, `fixed_password`, `protocol`, `default_port`) but is hardcoded rather than fetched. One model (`ST3DH`) is deliberately marked `pending_spec` to exercise the disabled + "(coming soon)" option state, even though a seed device already uses it — plausible (a driver can be pulled for re-certification after devices are already deployed on it), and deliberately chosen rather than left untested.
- **Source↔brand mapping**: v1 lets `source` (DLMS/Modbus) be picked independently of brand/model with no cross-validation. For the 12 seed devices, CEWE/Mitsubishi are seeded as DLMS and SMART TCC as Modbus (matching each catalog model's `protocol` field) purely for a realistic-looking seed set — the form itself still lets you pick either source for any brand, unrestricted, exactly like v1.
- **`group_name`**: present in v1's zod schema but never rendered on this page (dead in the UI, at least in the file read) — omitted here too, since replicating the page means replicating what it actually shows.
- **Meter Serial is always blank in the form, on purpose (matching v1, not fixing it)**: v1's device-detail-load effect (`form.setFieldsValue({...})`) never includes a `meter` key, so the read-only "Meter Serial" field shows its placeholder even when editing a device that has one. The **tree row** does show the real `meter_serial` (that data comes from a different v1 payload, `DeviceTreeItem`, which does carry it) — so the two panels are inconsistent in v1 itself, and both mockup variants replicate that inconsistency rather than "fixing" it.
- **No loading spinners / async fetch states**: v1's tree and detail panel both show a `Spin` while their real API calls are in flight. There's no backend here (out of scope per the original brief), so those states aren't reproduced — this is a UI-parity exercise, not a data-fetching one.
- **Create/Update/Delete/Disconnect/Reconnect are "live"** (mutate local `devices` state, with realistic delays, toasts, and a brief `Connecting → Online` transition on create/reconnect) rather than no-ops — this exercises each library's loading/disabled-button and toast/confirm patterns for real, which is more useful for a library decision than three inert buttons. Validation is a lightweight hand-rolled version of v1's real zod schema (required fields, IP/serial-port pattern, numeric bounds) — not the full schema, but the same rules, identically applied in both variants.
- **Mantine version**: `pnpm add @mantine/core` resolved to **v9.5.1** (today's actual latest), used as-is.
