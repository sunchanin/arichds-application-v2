import { App, Card, DatePicker, Empty, Flex, Select, Space, Table, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs, { type Dayjs } from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiRequestError, api, isLicenseLapsed, type RecordsCell, type RecordsGrid, type RecordsRow } from "../api";

const { RangePicker } = DatePicker;
const { Text } = Typography;

/** Shown where a logger this row has no name for would go. */
const NOTHING = "—";

/** The sentinel the "All site groups" option carries. */
const ALL = "all";

/** The default window: the last 7 days ending today. */
const DEFAULT_DAYS = 7;

const METER_WIDTH = 200;
const LOGGER_WIDTH = 80;
const DATE_WIDTH = 90;

/**
 * Render one cell's text.
 *
 * The first three spellings are **v1's own** (SPEC §3.5), which the customer
 * already reads: a complete day is the bare count, a short day carries how many
 * it is short by, and a day with nothing at all says so in words — because `0`
 * alone next to a column of numbers reads as a rendering bug, not as data.
 */
function cellText(cell: RecordsCell): string {
  switch (cell.status) {
    case "missing":
      return "0 (Missing)";
    case "short":
      // `expected` is non-null on every status but `missing`, so the fallback
      // is unreachable — and it prints the bare count rather than inventing a
      // shortfall, because "88 (88)" would read as data instead of as a bug.
      return cell.expected === null ? String(cell.count) : `${cell.count} (${cell.count - cell.expected})`;
    case "period_changed":
      return `${cell.count} (period changed)`;
    default:
      return String(cell.count);
  }
}

/**
 * Records (M5b-2) — is the stored load-profile data complete?
 *
 * One row per `(meter, logger)`, one column per local calendar date, each cell
 * carrying that day's Interval Reading count against what the meter's own
 * capture period says it should be.
 *
 * **It never talks to a meter**, and has no Read now button: every number here
 * is counted out of rows the meter itself recorded and the writer (#15) or the
 * Scheduler's job (#16) stored. Reading a meter lives on the Devices page.
 *
 * **The Logger column is part of the row's identity, never a merge key**
 * (CONTEXT.md — Interval Reading). A Prometer 100 runs Logger 1 at 900 s and
 * Logger 2 at 300 s on one physical meter at the same time, so the two have
 * genuinely different complete days and cannot share a line.
 *
 * **A complete day is `86400 / interval_sec`, not 96.** The server computes it
 * from the period stored on the rows, and this page only renders the answer —
 * so the constant SPEC §3.5 forbids appears in neither.
 *
 * **The only filter is site group**, applied client-side over the rows already
 * loaded: the grid's whole value is scanning every meter at once, and a
 * brand/model/device cascade would answer no completeness question. Load
 * Profile is where you go for the detail behind a suspicious cell.
 */
export function Records() {
  const { message } = App.useApp();

  const [site, setSite] = useState<string>(ALL);
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(DEFAULT_DAYS - 1, "day"), dayjs()]);

  // The loaded grid is stored with the range it answers, so a grid belonging to
  // the *previous* range is never rendered under the new one.
  const [loaded, setLoaded] = useState<{ scope: string; grid: RecordsGrid } | null>(null);
  const [loading, setLoading] = useState(false);

  const surface = useCallback(
    (err: unknown, fallback: string) => {
      // Checked first, everywhere: a license that lapsed under a signed-in
      // operator must take them back to Activation, not show a toast.
      if (isLicenseLapsed(err)) {
        window.location.reload();
        return;
      }
      message.error(err instanceof ApiRequestError ? err.message : fallback);
    },
    [message],
  );

  // Minutes to ADD to UTC to reach this browser's local time — ICT is +420,
  // which is the opposite sign to what `getTimezoneOffset()` returns.
  const utcOffsetMinutes = -new Date().getTimezoneOffset();

  const [from, to] = range;
  const startDate = from.format("YYYY-MM-DD");
  const endDate = to.format("YYYY-MM-DD");

  /** Which range the grid on screen must belong to. */
  const scope = `${startDate}|${endDate}|${utcOffsetMinutes}`;
  const grid = loaded?.scope === scope ? loaded.grid : null;

  useEffect(() => {
    let current = true;
    // The setState lands in a promise callback once the API answers; only the
    // spinner is set synchronously, which is the "subscribe to an external
    // system" case the rule's own documentation permits — the same exemption
    // Devices.tsx, App.tsx and LoadProfile.tsx already take for their fetches.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    void api
      .records(startDate, endDate, utcOffsetMinutes)
      .then((result) => {
        // A slower earlier request must not overwrite a newer answer, and must
        // not un-set the spinner a newer request turned on.
        if (current) setLoaded({ scope: `${startDate}|${endDate}|${utcOffsetMinutes}`, grid: result });
      })
      .catch((err: unknown) => {
        if (current) {
          setLoaded(null);
          surface(err, "Could not load the Records grid.");
        }
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [startDate, endDate, utcOffsetMinutes, surface]);

  // The one call that paints the grid also paints its filter — the site values
  // are whatever the returned rows carry, so the endpoint needs no site
  // parameter and the page needs no second request.
  const siteOptions = useMemo(
    () => [
      { value: ALL, label: "All site groups" },
      ...[...new Set((grid?.rows ?? []).map((row) => row.site_name))]
        .sort((a, b) => a.localeCompare(b))
        .map((value) => ({ value, label: value })),
    ],
    [grid],
  );

  const rows = useMemo(
    () => (grid?.rows ?? []).filter((row) => site === ALL || row.site_name === site),
    [grid, site],
  );

  const columns = useMemo<ColumnsType<RecordsRow>>(
    () => [
      { title: "Meter", dataIndex: "device_name", key: "device_name", width: METER_WIDTH, fixed: "left" },
      {
        // A meter's loggers are separate lines with separate expected counts.
        // Null only for a meter that recorded nothing at all in the range —
        // there is no logger to name, and the row is still here on purpose.
        title: "Logger",
        dataIndex: "logger_id",
        key: "logger_id",
        width: LOGGER_WIDTH,
        fixed: "left",
        render: (loggerId: number | null) => loggerId ?? NOTHING,
      },
      ...(grid?.dates ?? []).map((date, index) => ({
        title: dayjs(date).format("MM-DD"),
        key: date,
        width: DATE_WIDTH,
        render: (_: unknown, row: RecordsRow) => {
          const cell = row.cells[index];
          if (!cell) return NOTHING;
          const text = (
            // Theme semantics, never colour literals: a re-theme must carry the
            // grid with it (AppShell.tsx states the rule).
            <Text type={CELL_TYPE[cell.status]}>{cellText(cell)}</Text>
          );
          return cell.status === "period_changed" ? (
            <Tooltip
              title={`More than one capture period this day. Expected ${cell.expected} at ${cell.interval_sec} s.`}
            >
              {text}
            </Tooltip>
          ) : (
            text
          );
        },
      })),
    ],
    [grid],
  );

  const onRangeChange = (dates: (Dayjs | null)[] | null) => {
    // `allowClear={false}` means the picker cannot hand back an empty range, but
    // its type permits one — so the range is only replaced when both ends are
    // real, and the previous one stands otherwise.
    const [start, end] = dates ?? [];
    if (!start || !end) return;
    setRange([start, end]);
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card size="small">
        <Flex gap="small" wrap align="center">
          <Select
            value={site}
            onChange={setSite}
            options={siteOptions}
            style={{ minWidth: 200 }}
            aria-label="Site group"
          />
          <RangePicker
            value={range}
            onChange={onRangeChange}
            allowClear={false}
            // Only the future is out of reach. v1 also clamped the past to its
            // 90-day retention window; v2 has no retention job until M5c, so
            // clamping here would hide days that really are in the table.
            disabledDate={(current) => current.isAfter(dayjs().endOf("day"))}
          />
        </Flex>
      </Card>

      {grid !== null && grid.rows.length === 0 ? (
        <Card>
          <Empty description="No meters yet" />
        </Card>
      ) : (
        <Card size="small">
          <Table<RecordsRow>
            size="small"
            rowKey={(row) => `${row.device_id}-${row.logger_id ?? "none"}`}
            loading={loading}
            dataSource={rows}
            columns={columns}
            scroll={{ x: METER_WIDTH + LOGGER_WIDTH + (grid?.dates.length ?? 0) * DATE_WIDTH }}
            // No pager: 31 columns by at most 30 meters is one screenful of
            // rows, and the range picker above is already the only control that
            // changes how much there is.
            pagination={false}
          />
        </Card>
      )}
    </Space>
  );
}

/**
 * The theme role each state renders in.
 *
 * `complete` is deliberately absent — an ordinary count is ordinary text, and
 * marking every good day green would leave nothing for the bad ones to stand
 * out against.
 */
const CELL_TYPE: Record<RecordsCell["status"], "warning" | "danger" | undefined> = {
  complete: undefined,
  short: "warning",
  missing: "danger",
  period_changed: "warning",
};
