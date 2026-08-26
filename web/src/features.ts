/**
 * The in-shell page list and what each page is entitled to (issue 012).
 *
 * `Page`, `PAGES` and `toPage` moved here from `App.tsx` so the page list and
 * the entitlement mapping live in one module and cannot drift: a page added to
 * one and forgotten in the other is a `tsc -b` error, not a silently-always-
 * shown menu entry.
 *
 * **The mapping is not enforcement.** The server gate (`require_feature`,
 * `app/src/arichds/api/deps.py`) is what refuses an unlicensed page, and issue
 * 012 changed none of it. This module only decides what the left nav
 * *advertises* and, through `pageFeatureKey`, what `App.tsx` renders instead of
 * a page reached without its entry. If the two ever disagree the server wins
 * and the customer sees a refusal — which is the safe direction.
 *
 * Each entry's key is the key that page's own API is gated on, verified
 * against the routers rather than guessed:
 * `billing`/`load_profile`/`records`/`energy_summary`/`special_days`/`battery`
 * from the router-level `dependencies=[...]`, and — the one that is not
 * obvious — **Export Format is gated on `load_profile`**, because
 * `/api/settings/export-format` owns the Load Profile CSV's format
 * (`api/settings.py`, `GET`/`PUT` both `require_feature("load_profile")`).
 */

/** The in-shell pages. Every other menu key belongs to a milestone that has not shipped. */
export type Page =
  | "devices"
  | "load-profile"
  | "records"
  | "billing"
  | "energy-summary"
  | "holidays"
  | "special-days"
  | "battery"
  | "export-format"
  | "app-log"
  | "users"
  | "settings"
  | "database-destination"
  | "file-upload-destination";

export const PAGES: readonly Page[] = [
  "devices",
  "load-profile",
  "records",
  "billing",
  "energy-summary",
  "holidays",
  "special-days",
  "battery",
  "export-format",
  "app-log",
  "users",
  "settings",
  "database-destination",
  "file-upload-destination",
];

/** Read a menu key as a page, falling back to Devices for anything unrecognised. */
export function toPage(key: string): Page {
  return PAGES.includes(key as Page) ? (key as Page) : "devices";
}

/**
 * The three — and only three — things a page can be, with no implicit default.
 *
 * - `feature`: advertised only while `key` is in `LicenseStatus.enabled_features`.
 * - `always`: never hidden by a licence. The customer goes here when something
 *   is wrong, so a licence problem must not take it away.
 * - `never`: the page exists and works, but nothing advertises it. Distinct
 *   from an empty feature key: a "never" page reached directly renders
 *   normally, because its absence from the nav is not a licence matter.
 */
export type PageEntitlement =
  | { readonly kind: "feature"; readonly key: string }
  | { readonly kind: "always" }
  | { readonly kind: "never" };

/**
 * Every page, exhaustively. `Record<Page, …>` is the "visible failure" issue
 * 012 asks for: adding a `Page` without an entry here fails `pnpm build`.
 */
export const PAGE_ENTITLEMENT: Record<Page, PageEntitlement> = {
  // `/api/devices` is deliberately never feature-gated (decision 7, issue #22):
  // a meter is licensed by count and by Meter Activation Code, not by a key.
  devices: { kind: "always" },
  "load-profile": { kind: "feature", key: "load_profile" },
  records: { kind: "feature", key: "records" },
  // The page needs `billing` alone. `billing_excel_export` and
  // `billing_image_export` gate *controls on it* (D14) — a licence with
  // `billing` and neither export still shows Billing, buttons refusing.
  billing: { kind: "feature", key: "billing" },
  "energy-summary": { kind: "feature", key: "energy_summary" },
  // The calendar feeds the summary's Holiday bucket and `/api/holidays` gates
  // on the same key (decision 18, issue #28) — one purchase, two pages.
  holidays: { kind: "feature", key: "energy_summary" },
  "special-days": { kind: "feature", key: "special_days" },
  battery: { kind: "feature", key: "battery" },
  // Not a key of its own: this page is the Load Profile CSV's format, and
  // `/api/settings/export-format` is gated on `load_profile`.
  "export-format": { kind: "feature", key: "load_profile" },
  // Ops-only, and no exception to the rule (D6). `.env FEATURES` empty/unset
  // expands to every key, so this is on for every default install and hides
  // only where an operator deliberately excluded it — on a machine where the
  // page 403s anyway. `AppLog.tsx`'s own inline Result stays the backstop.
  "app-log": { kind: "feature", key: "app_log" },
  // Role-gated, not feature-gated; `AppShell` still hides it from a `user`.
  users: { kind: "always" },
  // Never hidden, by decision: it is where the customer goes when something is
  // wrong, and its License card is how support says "read what you have" (D9).
  settings: { kind: "always" },
  "database-destination": { kind: "feature", key: "database_destination" },
  // Presentation-only, no transport and no feature key (ADR 0016, issue #37),
  // so there is nothing a customer can do with it (D7, issue 012). Unhide it
  // when M8 / SPEC §3.8 gives it a transport — and give it a key then.
  "file-upload-destination": { kind: "never" },
};

/**
 * The feature key *page* needs, or `null` when a licence has no say over it.
 *
 * `null` for both `always` and `never`, and that is the point: neither can
 * produce the "not enabled" message, because for neither is a missing entry a
 * licence matter.
 */
export function pageFeatureKey(page: Page): string | null {
  const entitlement = PAGE_ENTITLEMENT[page];
  return entitlement.kind === "feature" ? entitlement.key : null;
}

/** Whether the left nav should advertise *page* on a machine with *enabledFeatures*. */
export function isPageAdvertised(page: Page, enabledFeatures: readonly string[]): boolean {
  const entitlement = PAGE_ENTITLEMENT[page];
  switch (entitlement.kind) {
    case "always":
      return true;
    case "never":
      return false;
    case "feature":
      return enabledFeatures.includes(entitlement.key);
  }
}

/**
 * English names for every key in the backend's `FEATURE_KEYS`, for the License
 * card's "Enabled features" row (D12).
 *
 * All eleven, `app_log` included: the row says what this machine has, and
 * omitting the ops-only key would make it quietly incomplete.
 * `app/tests/test_nav_feature_contract.py` is the tripwire that keeps this list
 * and `FEATURE_KEYS` from drifting.
 */
export const FEATURE_LABELS: Record<string, string> = {
  app_log: "App Log",
  auto_capture: "Auto Capture",
  battery: "Battery",
  billing: "Billing",
  billing_excel_export: "Billing Excel Export",
  billing_image_export: "Billing Image Export",
  database_destination: "Database Destination",
  energy_summary: "Energy Summary",
  load_profile: "Load Profile",
  records: "Records",
  special_days: "Special Days",
};
