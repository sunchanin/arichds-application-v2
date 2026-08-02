# Setup: Ant Design v5 on Next.js 16 App Router + React 19

This file is our **project wiring** (exact `layout.tsx` / `ThemeProvider` code).
For the current upstream API, query context7: `/ant-design/ant-design` →
"Use Ant Design v5 with Next.js App Router, AntdRegistry, React 19 patch".

This stack has three load-bearing pieces. If first-screen styles flash unstyled
(FOUC), `Modal`/`message` behave oddly, or you get "use client" errors, the
cause is almost always one of these.

## 1. Install

```bash
bun add antd @ant-design/icons @ant-design/nextjs-registry @ant-design/v5-patch-for-react-19
```

## 2. React 19 compatibility patch

Ant Design v5 was written for React 16–18. Its imperative APIs (`Modal.confirm`,
`message`, `notification` rendered via `unmountComponentAtNode` / the old render
API) break under React 19. The official fix is a one-line patch imported **once**
at the app entry, before any antd usage.

`app/layout.tsx` (top of file):

```tsx
import "@ant-design/v5-patch-for-react-19";
```

Importing it once at the root is enough — it monkey-patches antd's internals for
the whole app. Forgetting it is the #1 cause of "Modal opens but does nothing"
type bugs on this stack. (Antd **v6 drops this requirement** — remove the patch
import when/if we upgrade.)

> Prefer `App.useApp()` (see `patterns.md`) over the static `message.xxx()` /
> `Modal.confirm()` APIs anyway — the hook-based ones are both theme-correct and
> less affected by the React 19 gap.

## 3. AntdRegistry (SSR style extraction — prevents FOUC)

Antd uses CSS-in-JS (`@ant-design/cssinjs`). Without help, styles are only
generated on the client, so the server-rendered HTML ships unstyled and the page
flashes before hydration. `AntdRegistry` collects the styles generated during
SSR and inlines them into the initial HTML.

`app/layout.tsx`:

```tsx
import "@ant-design/v5-patch-for-react-19";
import type { ReactNode } from "react";
import { AntdRegistry } from "@ant-design/nextjs-registry";
import ThemeProvider from "./ThemeProvider";

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AntdRegistry>
          <ThemeProvider>{children}</ThemeProvider>
        </AntdRegistry>
      </body>
    </html>
  );
}
```

`layout.tsx` itself stays a **Server Component** — `AntdRegistry` and our
`ThemeProvider` are the client boundary, so we don't pay for making the whole
layout client-side.

## 4. ThemeProvider (client component)

`ConfigProvider`, the `theme` object, and `App` (for `App.useApp()`) are all
client-only. Wrap them in a dedicated client component so `layout.tsx` can stay
on the server. `<App>` here also provides the context that `App.useApp()` reads.

`app/ThemeProvider.tsx`:

```tsx
"use client";

import type { ReactNode } from "react";
import { App, ConfigProvider, theme } from "antd";

const themeConfig = {
  // algorithm: theme.darkAlgorithm, // uncomment for dark mode
  token: {
    colorPrimary: "#1677ff",
    borderRadius: 6,
  },
};

export default function ThemeProvider({ children }: { children: ReactNode }) {
  return (
    <ConfigProvider theme={themeConfig}>
      <App>{children}</App>
    </ConfigProvider>
  );
}
```

Token and algorithm details → `theming.md`. Why `<App>` matters → `patterns.md`.

## 5. Server vs Client component boundary

Rule of thumb: **antd components render in Client Components; data fetching stays
in Server Components.**

- A `page.tsx` can be a Server Component that fetches data and passes it as props
  to a `"use client"` component that renders antd.
- Any file that imports `Form`, `Table`, `Modal`, `Button`, `useState`,
  `App.useApp()`, etc. needs `"use client"` at the top.
- Keep the client boundary as low in the tree as practical so you don't turn
  large server subtrees into client bundles.

```tsx
// app/users/page.tsx  — Server Component (no "use client")
import UsersTable from "./UsersTable";

export default async function UsersPage() {
  const { rows, total } = await fetchUsers({ page: 1, pageSize: 20 });
  return <UsersTable initialRows={rows} total={total} />;
}
```

```tsx
// app/users/UsersTable.tsx — Client Component
"use client";
import { Table } from "antd";
// ...renders the antd Table, owns pagination state
```

## Gotcha: subcomponent dot-notation under App Router

Two *separate* reasons push us toward `options`/`items` props — don't conflate them:

1. **Deprecation (not RSC-specific).** In antd v5, `<Select.Option>` children are
   deprecated in favour of the `options` prop — true regardless of Server vs Client.
   Feed `Select`/`Menu` via `options`/`items`.
2. **RSC boundary.** antd's official FAQ notes that *accessing* dot-access
   subcomponents like `<Select.Option>` / `<Form.Item>` **from a Server Component**
   can throw. The documented fix is adding `"use client"` to that file (or wrapping
   the subcomponent in a client component) — not switching to `options`.

So: use `options`/`items` because the children API is deprecated, and keep antd in
`"use client"` files because of the RSC boundary. Both apply; they're different
problems.
