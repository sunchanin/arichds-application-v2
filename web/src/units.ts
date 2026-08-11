/**
 * The kilo<->base display-unit conversion — the TypeScript twin of the
 * backend's `arichds.capture._render_shared.scale_value` /
 * `scale_label` (`app/src/arichds/capture/_render_shared.py`).
 *
 * Deliberately duplicated rather than shared: the backend and the web app
 * are two different runtimes with no shared module boundary, and the rule
 * this feature must never break — a value and its unit label always move
 * together — is exactly as important here as it is in the capture
 * renderers. Keep the two in sync by hand; there is nothing to import
 * between them.
 *
 * The API payload is never touched — every readings endpoint keeps
 * returning kWh/kvarh/kW/kvar regardless of this setting (CLAUDE.md's
 * write-time normalization invariant). Conversion happens here, at render
 * time, in the page that draws the column.
 */

import { useEffect, useState } from "react";

import { api, type DisplayUnitScale } from "./api";

export type { DisplayUnitScale };

/**
 * The current `display_unit_scale`, fetched once on mount.
 *
 * Every in-shell page mounts fresh on navigation (`App.tsx` renders exactly
 * one page at a time), so a value saved on the Settings page is picked up
 * the next time a caller navigates to a page using this hook — the same
 * "fetched on mount, no shared store" pattern `Billing.tsx`'s own
 * `CaptureSettingsCard` already uses for `capture_dir`. A fetch failure is
 * swallowed and the default (`"kilo"`, today's behaviour) stands, matching
 * how `LoadProfile.tsx` already treats its own non-critical `catalog()` call
 * — losing the display-unit preference for one page load costs nothing a
 * toast would recover, and every number is still correct, just unscaled.
 */
export function useDisplayUnitScale(): DisplayUnitScale {
  const [scale, setScale] = useState<DisplayUnitScale>("kilo");

  useEffect(() => {
    api
      .displaySettings()
      .then((data) => setScale(data.display_unit_scale))
      .catch(() => {
        // Non-critical — see the docstring above.
      });
  }, []);

  return scale;
}

/** Which of the four convertible quantities a column holds. */
export type UnitKind = "energy" | "reactiveEnergy" | "power" | "reactivePower";

const KILO_LABELS: Record<UnitKind, string> = {
  energy: "kWh",
  reactiveEnergy: "kvarh",
  power: "kW",
  reactivePower: "kvar",
};

const BASE_LABELS: Record<UnitKind, string> = {
  energy: "Wh",
  reactiveEnergy: "varh",
  power: "W",
  reactivePower: "var",
};

/** The unit label for *kind* under *scale* — `kWh`/`kvarh`/`kW`/`kvar` under
 * `"kilo"`, `Wh`/`varh`/`W`/`var` under `"base"`. */
export function unitLabel(kind: UnitKind, scale: DisplayUnitScale): string {
  return scale === "kilo" ? KILO_LABELS[kind] : BASE_LABELS[kind];
}

/**
 * Convert *value* for display under *scale*.
 *
 * `"kilo"` is a no-op (today's behaviour). `null`/`undefined` pass through
 * unchanged — "the meter never captured this" must still render as the
 * em dash every measurement column already gives an absent value, never
 * `NaN` — and a genuine `0` scales like any other number (`value == null`,
 * never falsy-testing `value`, mirrors `Billing.tsx`/`LoadProfile.tsx`'s own
 * `num()` helpers).
 */
export function scaleValue(value: number | null | undefined, scale: DisplayUnitScale): number | null | undefined {
  if (scale === "kilo" || value == null) return value;
  return value * 1000;
}
