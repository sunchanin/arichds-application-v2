---
name: antd-ui
description: >-
  Base UI guideline for this project: Ant Design v5 on Next.js 16 App Router +
  React 19 + TypeScript. Use this skill WHENEVER building, editing, or reviewing
  any UI in this repo — pages, forms, tables, modals, layouts, buttons, inputs,
  selects, theming, or toasts/notifications. Trigger it even when the user says
  "add a page/form/table/dialog", "build the dashboard", "wire up the UI", or
  names an antd component, without saying "antd". It encodes the React 19 + antd
  compat setup (v5-patch, AntdRegistry), the Server/Client boundary rules, and
  the project's mandatory conventions (vertical forms, server-side pagination,
  App.useApp(), theme tokens over hardcoded values). Consult it before writing
  UI code so you don't reintroduce FOUC, "use client" errors, or off-convention
  components.
---

# antd-ui — Project UI workflow (Ant Design v5)

This project builds UI with **Ant Design v5** on **Next.js 16 (App Router) +
React 19 + TypeScript**. This skill is a **workflow**: it holds the project's
locked decisions and project-correct snippets inline (so it works offline), and
points you to **context7** to confirm the **current upstream API** — exhaustive
props, exact token names, anything the local snippets don't cover. Antd predates
React 19, so a few setup pieces are non-negotiable — get them wrong and you get
FOUC, runtime errors, or broken theming.

## Workflow — run these phases for any UI task

### Phase 0 · Is the app wired for antd? *(first UI task only)*
Check `app/layout.tsx` wraps `children` in `<AntdRegistry>` and imports
`@ant-design/v5-patch-for-react-19`, and that a client `ThemeProvider` holds
`ConfigProvider` + `<App>`.
- **Not wired?** → fix first using `references/setup-nextjs.md` (our exact code).
- **Verify:** `app/layout.tsx` is still a Server Component (no `"use client"`).

### Phase 1 · Pick the Server/Client boundary
Data fetching stays in Server Components (`page.tsx`); anything importing antd or
using state goes in a `"use client"` leaf, kept as low in the tree as practical.
- **Verify:** every file importing antd starts with `"use client"`.

### Phase 2 · Start from the project snippet, verify props on context7
Copy the project-correct snippet from `references/components.md` (it already
encodes the conventions). When you need a prop the snippet doesn't show, or want
to confirm the current API, query context7 (see **Fetching live docs**). The
snippet's *composition* is the project rule; context7 covers the *prop surface*.

### Phase 3 · Apply the project conventions *(non-negotiable, see below)*
Vertical forms · server-side pagination · `App.useApp()` feedback · theme tokens.

### Phase 4 · Self-check before finishing
Run the checklist in `references/patterns.md` (boundary, vertical form, server
pagination + `total`, `App.useApp()`, tokens, `options`/`items` props, patch +
registry wired).

## The non-negotiables (project policy — NOT docs, never fetch these)

**Setup (or the stack breaks):**
1. **React 19 patch** — import `@ant-design/v5-patch-for-react-19` **once** at the
   app entry, or `Modal`/`message`/`notification` silently misbehave. *(antd v6
   drops this need — keep it while we're on v5.)*
2. **`<AntdRegistry>`** from `@ant-design/nextjs-registry` must wrap `children` in
   `app/layout.tsx` — SSR style extraction, or the first screen flashes unstyled.
3. **`"use client"`** — antd components are client components; never import them
   into a Server Component.
4. **`ConfigProvider` + `<App>`** live in a **client** `ThemeProvider`, nested
   inside `<AntdRegistry>`.

**Conventions (apply every time — rationale in `references/patterns.md`):**
- **Forms:** `layout="vertical"` always.
- **Tables:** server-side pagination — pass `total`, refetch on `onChange`. Never
  dump a full dataset client-side.
- **Feedback:** `App.useApp()` → `message`/`modal`/`notification`. Never the
  static `message.xxx()` imports (they render outside the theme context).
- **Styling:** spacing/colors from **theme tokens** (`theme.useToken()` / `theme`
  prop), not hardcoded hex/px.
- **Subcomponents:** feed `Select`/`Menu` via `options`/`items` props, not
  `.Option`/`.Item` children (RSC dot-notation caveat).

## Fetching live docs from context7

Use context7 to **confirm current props/tokens or fill gaps the local snippets
don't cover** — not as a mandatory step before every component. Resolve isn't
needed — use these IDs directly:

| Library ID | Use for |
|------------|---------|
| `/ant-design/ant-design` | Components, Next.js setup, React 19 compat, `App`, forms, tables, theming |
| `/websites/ant_design` | Alternative antd docs source if the first lacks coverage |

Ready-made queries (pass to `query-docs`):

| Task | `query-docs` query |
|------|--------------------|
| Next.js setup / SSR | "Use Ant Design v5 with Next.js App Router, AntdRegistry, React 19 patch" |
| Form | "antd Form layout vertical, Form.Item rules validation, Form.useForm instance methods" |
| Table | "antd Table server-side pagination, TableColumnsType, onChange, rowKey" |
| Select | "antd Select options prop, multiple mode, showSearch, server-driven search" |
| Modal | "antd Modal open state vs App.useApp modal.confirm" |
| Feedback | "antd App.useApp message notification vs static methods" |
| Theming | "antd v5 ConfigProvider theme tokens, algorithm dark compact, components override, useToken" |

Anything not antd-specific (a JS API, a Next.js convention) → resolve the right
library first with `resolve-library-id`.

## References (project-specific — kept local because they are decisions, not docs)

| File | Read it when… |
|------|---------------|
| `references/setup-nextjs.md` | Wiring `layout.tsx` / `ThemeProvider` — our exact code + boundary rules |
| `references/patterns.md` | The conventions above, with full rationale + the finish checklist |
| `references/components.md` | Project-correct snippets to copy (Form, Table, Select, Modal…) + context7 query for full props |
| `references/theming.md` | Consuming tokens (project decisions) + context7 query for the token/algorithm API |

## Required packages

```bash
bun add antd @ant-design/icons @ant-design/nextjs-registry @ant-design/v5-patch-for-react-19
```
