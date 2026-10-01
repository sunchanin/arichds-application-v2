/**
 * The period-total row for the Summary Report tab (issue #36) — pure
 * arithmetic, deliberately isolated from React/antd/`./units` so it can be
 * exercised by a plain `node` process — this repo's `web/` has no test
 * runner.
 *
 * Never stored anywhere (ADR 0012 — the Energy Summary is derived on every
 * request); this module only folds the days already fetched for the current
 * response.
 */
import type { EnergySummaryDay } from "./api";

/** The eight kWh columns, in display order — the single list that drives
 * both the table's columns and the total row, so a total can never land
 * under the wrong heading. */
type EnergyValueKey = Exclude<keyof EnergySummaryDay, "date">;

export const ENERGY_COLUMNS: readonly { title: string; key: EnergyValueKey }[] = [
  { title: "Peak Import", key: "peak_import_kwh" },
  { title: "Off-Peak Import", key: "offpeak_import_kwh" },
  { title: "Holiday Import", key: "holiday_import_kwh" },
  { title: "Total Import", key: "total_import_kwh" },
  { title: "Peak Export", key: "peak_export_kwh" },
  { title: "Off-Peak Export", key: "offpeak_export_kwh" },
  { title: "Holiday Export", key: "holiday_export_kwh" },
  { title: "Total Export", key: "total_export_kwh" },
];

/**
 * The eight column totals, formatted with `render`, in `ENERGY_COLUMNS`
 * order — or `null` when there is nothing to total (D10: absent, not zero,
 * so a total row never renders under "No data in range").
 *
 * Sums the raw kWh values first, then formats once per column (`render` is
 * what applies the kilo/base display scale) — never rounds per day, so the
 * total agrees with what the same values would sum to by hand.
 */
export function energyTotalCells(
  days: EnergySummaryDay[],
  render: (value: number) => string,
): string[] | null {
  if (days.length === 0) return null;
  return ENERGY_COLUMNS.map(({ key }) => render(days.reduce((sum, day) => sum + day[key], 0)));
}
