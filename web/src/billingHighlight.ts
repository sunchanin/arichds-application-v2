/**
 * Which History row is "the latest bill" (ui-audit ticket 09).
 *
 * The rule is by **bill date**, never by row index: a page sorted oldest-first,
 * or a date filter that hides the newest period, still tints the newest period
 * *shown*, and an empty table tints nothing. It resolves a **row**, not a date:
 * with "All devices" several meters routinely close on the same instant, and
 * v1 (#49) tints one row, not one per device — the tie goes to the lowest id,
 * which is deterministic across re-renders. Kept as a pure function so its
 * behaviour can be proven outside the browser (`web/` has no test runner —
 * see `web/scripts/latest-bill-evidence.mjs`).
 *
 * @param rows The rows shown, in table order.
 * @returns The id of the row to tint, or null when there are no rows.
 */
export function latestBillRowId(rows: readonly { id: number; bill_date: string }[]): number | null {
  let latest: { id: number; bill_date: string } | null = null;
  for (const row of rows) {
    if (latest === null) {
      latest = row;
      continue;
    }
    const newer = Date.parse(row.bill_date) - Date.parse(latest.bill_date);
    if (newer > 0 || (newer === 0 && row.id < latest.id)) latest = row;
  }
  return latest === null ? null : latest.id;
}
