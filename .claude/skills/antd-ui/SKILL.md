---
name: antd-ui
description: >-
  Base UI guideline for ARICHDS Application v2: Ant Design v6 on Vite + React 19
  + TypeScript (a client-rendered SPA served by FastAPI at one origin — NOT
  Next.js, NOT SSR). Use this skill WHENEVER building, editing, or reviewing any
  UI in web/ — pages, forms, tables, modals, layouts, buttons, inputs, selects,
  theming, or toasts/notifications. Trigger it even when the user says "add a
  page/form/table/dialog", "build the page", "wire up the UI", or names an antd
  component, without saying "antd". It encodes the project's locked theme (deep
  teal, compact, light), the App.useApp() feedback rule, English-only UI, and
  the single-origin/no-SSR setup. Consult it before writing UI code so you stay
  on-convention.
---

# antd-ui — Project UI workflow (Ant Design v6, Vite SPA)

ARICHDS v2 builds UI with **Ant Design v6** on **Vite + React 19 + TypeScript**.
The built SPA is served by FastAPI from the same origin as `/api` (no nginx, no
CORS, **no SSR, no Next.js**). This skill holds the project's locked UI decisions.

> **The living reference is `web/src/` itself** — `main.tsx` (provider wiring),
> `theme.ts` (tokens), `App.tsx` (license-state routing), `pages/`. Read the
> real files before adding UI; they already encode every rule below. This skill
> is the *why* and the checklist; the code is the *what*.

## Stack facts (get these wrong and things break)

- **AntD v6** — the v5 React-19 compat shims are gone. Do **NOT** add
  `@ant-design/v5-patch-for-react-19` or `@ant-design/nextjs-registry`; they are
  v5/Next-only and wrong here.
- **Vite SPA, client-rendered** — there is no Server/Client boundary, no
  `"use client"`, no `app/layout.tsx`. Every component is a client component.
  Any guidance mentioning RSC, `page.tsx`, or `AntdRegistry` is from the old
  Next.js stack and does not apply.
- **One provider tree, set once in `web/src/main.tsx`**:
  `<ConfigProvider theme={arichdsTheme} locale={enUS}><AntdApp>…`. Never nest a
  second `ConfigProvider` with a competing theme.

## The non-negotiables (project policy)

1. **Theme is applied once, inherited everywhere.** Tokens live in
   `web/src/theme.ts`: `colorPrimary #0f766e` (deep teal), `borderRadius 6`,
   `algorithm: [defaultAlgorithm, compactAlgorithm]` (compact density, light
   mode). Adding a page = using these tokens, never re-declaring the theme.
   Changing brand feel = editing `theme.ts` only. This is the M0 decision (D4):
   re-themed AntD, not stock — the compact+teal combination is what makes it not
   look like default Ant Design.
2. **Feedback via `App.useApp()`** → `message` / `modal` / `notification`.
   Never the static `message.xxx()` / `Modal.confirm()` imports — they render
   outside the ConfigProvider theme (wrong colors, no compact). `<AntdApp>` is
   already mounted in `main.tsx` for this.
3. **Styling from theme tokens**, not hardcoded hex/px. Consume via
   `theme.useToken()` when a component needs a token value. Shared layout
   constants (e.g. `HEADER_HEIGHT`) live as exports in `theme.ts`, not inline
   magic numbers.
4. **Forms:** `layout="vertical"` always; validate with `Form.useForm` +
   `Form.Item` rules.
5. **Tables:** for any list that can grow (readings, events, devices across
   sites), paginate **server-side** — pass `total`, refetch on `onChange`.
   Never dump a full dataset into a client-side table. (M1's Monitor shows a
   handful of live devices and is fine unpaginated; the domain-module lists are
   not.)
6. **Subcomponents via props:** feed `Select`/`Menu` through `options`/`items`,
   not `.Option`/`.Item` children (in v6 the installed `.d.ts` marks `.Option`
   `@deprecated`). If you need the columns type, import it as
   `import type { ColumnsType } from "antd/es/table"` — top-level `antd` exposes
   it renamed to `TableColumnsType` in v6.
7. **English only.** No Thai strings in `web/` (SPEC §2 rules out i18n).
   `locale={enUS}`. v1 mixed Thai into the UI — do not carry it over.
8. **License-state routing, not URL routing** (M1 pattern, `App.tsx`): the app
   shows Activation vs the shell based on `GET /api/license/status`, and
   transitions live on activation (ADR 0001) — no reload. Later modules add
   in-shell navigation, but the top-level gate stays state-driven.

## Fetching current AntD docs (Context7 is NOT available here)

When you need a prop, token name, or API the local code doesn't show, do **NOT**
rely on training memory and do **NOT** try Context7 MCP tools — they are not
connected in this environment (verified 2026-08-04; any "use context7"
instruction silently degrades). Use the proven fallbacks:

- **WebFetch** the official docs: `https://ant.design/components/<name>` (append
  the component, e.g. `/table`, `/form`, `/config-provider`). For v6-specific
  changes, `https://ant.design/docs/react/migrate-v5-to-v6`.
- **Read the installed source**: `web/node_modules/antd/es/<component>/` — the
  `.d.ts` files are the exact current prop surface for the pinned version.

Confirm against the installed version (`antd` in `web/package.json`), not a
remembered one — v6 renamed/removed things v5 had.

## Self-check before finishing

- [ ] No `"use client"`, no `AntdRegistry`, no v5-patch import added.
- [ ] No second `ConfigProvider` / theme re-declared; tokens come from `theme.ts`.
- [ ] Feedback uses `App.useApp()`, not static `message.*`/`Modal.*`.
- [ ] Forms `layout="vertical"`; growable tables paginate server-side with `total`.
- [ ] `Select`/`Menu` fed via `options`/`items`.
- [ ] All user-facing strings English; no hardcoded hex/px where a token fits.
- [ ] `pnpm lint` and `pnpm build` pass (build fails on type errors).
