/**
 * The capture-mode seed the headless renderer plants before the SPA boots
 * (ADR 0017, issue #38).
 *
 * `app/src/arichds/capture/screenshot.py` calls
 * `Page.addScriptToEvaluateOnNewDocument` to set `window.__ARICHDS_CAPTURE__`
 * *before* navigation, alongside the session in `localStorage` (`auth.ts`).
 * Read once, here, at module load — never re-read on a later render, so a
 * page a human opens normally is never affected by whatever ran before it in
 * the same tab.
 *
 * Anything malformed is treated as absent: a broken global must not break
 * the page for a human. That is the regression this file exists to prevent —
 * every consumer of `captureRequest` must behave exactly as it does today
 * when this is `null`.
 */

/** What the renderer seeds — the state the Billing page needs driven by
 * something other than a click, because exactly ten periods is unreachable
 * through the UI (`PAGE_SIZE_OPTIONS` has no `10`) and the `bill_date`
 * bound needs instant precision the RangePicker cannot give it. */
export interface CaptureRequest {
  /** Which device's Billing History to show. */
  deviceId: number;
  /** The `meter_serial` filter (decision 7, issue #38) — `null` mirrors "no
   * filter", matching `BillingReading.meter_serial`'s own nullability. */
  meterSerial: string | null;
  /** Exclusive upper bound on `bill_date`, UTC. Must be chosen so the
   * anchor row's own `bill_date` is included — `_png_source_rows()` is
   * inclusive (`<=`), the API's `end` is exclusive (`<`). */
  endIso: string;
  /** The page size to request — large enough that every row
   * `_png_source_rows()` selected (at most ten) lands on page one. */
  pageSize: number;
}

declare global {
  interface Window {
    __ARICHDS_CAPTURE__?: unknown;
  }
}

function isCaptureRequest(value: unknown): value is CaptureRequest {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<CaptureRequest>;
  return (
    typeof candidate.deviceId === "number" &&
    (typeof candidate.meterSerial === "string" || candidate.meterSerial === null) &&
    typeof candidate.endIso === "string" &&
    typeof candidate.pageSize === "number"
  );
}

const rawCaptureRequest = typeof window !== "undefined" ? window.__ARICHDS_CAPTURE__ : undefined;

/**
 * The seeded capture request, or `null` when absent or malformed — read
 * once, at module load, per the module doc above.
 */
export const captureRequest: CaptureRequest | null = isCaptureRequest(rawCaptureRequest) ? rawCaptureRequest : null;
