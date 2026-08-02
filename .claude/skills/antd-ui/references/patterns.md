# Project conventions (and why)

These are the rules that make this codebase consistent. They're cheap to follow
and annoying to retrofit. Each one has a reason — follow the reason, not just the
letter.

## 1. Every Form uses `layout="vertical"`

```tsx
<Form layout="vertical" onFinish={onFinish}>...</Form>
```

**Why:** vertical layout keeps labels above fields, which stays readable on
narrow/responsive screens and gives every form in the app the same rhythm. Mixed
`horizontal`/`vertical` forms make the UI feel inconsistent. If a specific screen
genuinely needs horizontal (e.g. a compact inline filter bar), say so explicitly
in the code/PR — it's an exception, not a default.

## 2. Tables always use server-side pagination

Keep `page`, `pageSize`, sort, and filters in component state; refetch on
`onChange`; pass `total` to `pagination`.

```tsx
<Table
  dataSource={rows}                 // only the current page's rows
  pagination={{ current, pageSize, total }}  // total is REQUIRED
  onChange={(p) => refetch(p)}
/>
```

**Why:** the app is built for datasets that won't fit in the browser. Loading
everything to paginate client-side is slow, memory-hungry, and breaks the moment
the table grows. Server-side paging keeps payloads bounded and the UI honest
about how much data exists. Even for small tables, doing it this way means no
rewrite when the data grows. Full snippet in `components.md` → Table.

## 3. Feedback via `App.useApp()`, never static `message.*`

```tsx
// ✅ correct — theme-aware
const { message, modal, notification } = App.useApp();
message.success("Saved");

// ❌ wrong — renders outside ConfigProvider
import { message } from "antd";
message.success("Saved");
```

**Why:** the static `message.xxx()` / `Modal.confirm()` / `notification.xxx()`
functions render into a detached root that sits **outside** your
`ConfigProvider`. They don't see your theme tokens, locale, or algorithm — so a
toast won't match your dark mode or primary color, and antd itself warns about
this in v5. `App.useApp()` returns instances bound to the nearest `<App>` (mounted
in our `ThemeProvider`), so they render inside the theme context. As a bonus this
also sidesteps the React 19 imperative-API gap the v5-patch papers over.

Requirement: `<App>` must wrap the tree — it does, in `ThemeProvider.tsx`
(`setup-nextjs.md`).

## 4. Spacing & color come from theme tokens, not hardcoded values

```tsx
// ✅ correct
const { token } = theme.useToken();
<div style={{ padding: token.paddingLG, color: token.colorTextSecondary }} />

// ❌ wrong
<div style={{ padding: 24, color: "#8c8c8c" }} />
```

**Why:** hardcoded hex/px values drift out of sync with the theme. The moment
someone flips on `darkAlgorithm` or bumps `colorPrimary`, hardcoded values stay
stale and the UI looks broken in patches. Tokens are the single source of truth —
they recompute for dark/compact/custom themes automatically. Token catalog and
`useToken()` usage in `theming.md`.

Note: this project also has Tailwind available. For antd components and
antd-adjacent custom chrome, prefer antd tokens so everything tracks the same
theme. Reserve Tailwind for layout utilities that don't conflict with antd's
visual language.

## 5. Keep the Server/Client boundary clean

- Fetch data in Server Components (`page.tsx`), pass it as props.
- Put antd + interactivity behind `"use client"` components, as low in the tree
  as practical.

**Why:** antd is client-side; marking huge subtrees `"use client"` just to render
one button bloats the bundle and forfeits RSC benefits. Fetch on the server, hand
data to a small client leaf. Details and example in `setup-nextjs.md`.

---

## Quick self-check before finishing UI work

- [ ] Is the file that imports antd marked `"use client"`?
- [ ] Forms `layout="vertical"`?
- [ ] Table paginates server-side with `total` supplied?
- [ ] Toasts/dialogs via `App.useApp()` (no static `message.*` imports)?
- [ ] Custom spacing/colors from `theme.useToken()` / theme prop, not hardcoded?
- [ ] `Select`/`Menu` fed via `options`/`items` prop, not `.Option`/`.Item` children?
- [ ] (If first time) `v5-patch` imported + `<AntdRegistry>` wrapping in layout?
