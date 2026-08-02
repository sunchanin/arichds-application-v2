# Theming — fetch the token API from context7, keep the project wiring here

Antd v5 theming is a token system driven through `ConfigProvider`. The **API**
(token names, algorithms, component overrides, `useToken`) lives in the docs —
fetch it fresh from context7 rather than from a stale copy. The **project
decisions** are what this file keeps.

## Where to fetch the API

context7 library ID: **`/ant-design/ant-design`** → `query-docs` (fall back to
**`/websites/ant_design`** if coverage is thin).

| Need | context7 query |
|------|----------------|
| Token system (seed / map / alias) | "antd v5 design tokens seed map alias, ConfigProvider theme token" |
| Dark / compact theme | "antd theme.darkAlgorithm compactAlgorithm defaultAlgorithm combine array" |
| Per-component override | "antd ConfigProvider components token override, algorithm true derive" |
| Consume tokens in JSX | "antd theme.useToken hook, getDesignToken static" |
| Nested / local theme | "antd nested ConfigProvider local theme override merge" |

## Project decisions (these won't be in the docs)

1. **One `ConfigProvider`, in `app/ThemeProvider.tsx`** (a client component — see
   `setup-nextjs.md`). Change the theme there; **consume** tokens everywhere else.
2. **Never hardcode colors/spacing.** Read them from the active theme so dark/
   compact/custom switches stay consistent:

   ```tsx
   "use client";
   import { theme } from "antd";

   const { token } = theme.useToken();
   // ✅ token.colorBgContainer, token.paddingLG, token.colorBorder
   // ❌ "#fff", 24, "#d9d9d9"
   ```

3. **Tailwind coexists** but isn't the theme source: for antd components and
   antd-adjacent chrome, prefer antd tokens; reserve Tailwind for layout utilities
   that don't conflict with antd's visual language.

Tokens you'll reach for most: `colorPrimary`, `colorText`, `colorTextSecondary`,
`colorBgContainer`, `colorBgLayout`, `colorBorder`, `colorSuccess/Warning/Error`,
`borderRadius`, `fontSize`, and the `padding*` / `margin*` spacing scale — but
confirm exact names via context7, don't guess.
