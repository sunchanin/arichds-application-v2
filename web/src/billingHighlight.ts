/**
 * Which History row is "the latest bill" (ui-audit ticket 09).
 *
 * The rule is by **bill date**, never by row index: a page sorted oldest-first,
 * or a date filter that hides the newest period, still tints the newest period
 * *shown*, and an empty table tints nothing. Kept as a pure function so its
 * behaviour can be proven outside the browser (`web/` has no test runner).
 *
 * @param billDates ISO-8601 instants, one per row shown, in table order.
 * @returns The newest instant, or null when there are no rows.
 */
export function latestBillDate(billDates: readonly string[]): string | null {
  let latest: string | null = null;
  for (const billDate of billDates) {
    if (latest === null || Date.parse(billDate) > Date.parse(latest)) latest = billDate;
  }
  return latest;
}
