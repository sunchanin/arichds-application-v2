import { App, Button, Card, Empty, Flex, Result, Select, Space, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useState } from "react";

import { ApiRequestError, api, isLicenseLapsed, type LogEntry } from "../api";

const LINES_OPTIONS = [200, 500, 2000, 5000];
const DEFAULT_LINES = 500;

const LEVEL_OPTIONS = [
  { value: "", label: "All levels" },
  { value: "DEBUG", label: "DEBUG" },
  { value: "INFO", label: "INFO" },
  { value: "WARNING", label: "WARNING" },
  { value: "ERROR", label: "ERROR" },
  { value: "CRITICAL", label: "CRITICAL" },
];

const LEVEL_COLOR: Record<string, string> = {
  DEBUG: "default",
  INFO: "blue",
  WARNING: "gold",
  ERROR: "red",
  CRITICAL: "red",
};

/**
 * App Log (M7-4, issue #31) — a read-only tail viewer for the rotating
 * application log the process already writes.
 *
 * **Admin-only, and there is nothing to configure**: no filename (D1 — the
 * backend always reads exactly `arichds.log`), no Clear button (v1's button
 * silently emptied the *view*, never the file — SPEC §3.7), no live tailing.
 * Refresh always re-reads from disk (v1's bug, inverted): it is the only way
 * new entries appear.
 *
 * **A failed load keeps the last successfully loaded entries** and surfaces
 * the error through a toast — the one exception is `FEATURE_DISABLED`, shown
 * as an inline `Result` instead (D13), because "off" is the normal state for
 * this ops-only key on a customer machine, not something a toast should
 * interrupt a visit with. **Since issue 012 that is a backstop, not the
 * routine path**: the menu entry itself is now hidden when `app_log` is not
 * in the licence's effective set, so this `Result` is what a stale `page`, a
 * licence changed while the page was open, or a bookmark lands on — rarely,
 * rather than on every visit. Keep it: the server is still the authority, and
 * removing it would turn those into a blank page.
 */
export function AppLog() {
  const { message } = App.useApp();

  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [lines, setLines] = useState(DEFAULT_LINES);
  const [minLevel, setMinLevel] = useState("");
  const [loading, setLoading] = useState(false);
  const [disabled, setDisabled] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api
      .logs(lines, minLevel || undefined)
      .then((result) => {
        setDisabled(false);
        setEntries(result.items);
      })
      .catch((err: unknown) => {
        if (isLicenseLapsed(err)) {
          window.location.reload();
          return;
        }
        if (err instanceof ApiRequestError && err.code === "FEATURE_DISABLED") {
          setDisabled(true);
          return;
        }
        // Keep whatever was last loaded — a failed refresh must not clear the
        // view (that is exactly v1's bug, see the component doc above).
        message.error(err instanceof ApiRequestError ? err.message : "Could not load the App Log.");
      })
      .finally(() => setLoading(false));
  }, [lines, minLevel, message]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lines, minLevel]);

  if (disabled) {
    return <Result status="info" title="App Log is not enabled on this installation" />;
  }

  const columns: ColumnsType<LogEntry> = [
    { title: "Time", dataIndex: "timestamp", key: "timestamp", width: 200, render: (t: string | null) => t ?? "—" },
    {
      title: "Level",
      dataIndex: "level",
      key: "level",
      width: 110,
      render: (level: string | null) => (level == null ? "—" : <Tag color={LEVEL_COLOR[level]}>{level}</Tag>),
    },
    { title: "Logger", dataIndex: "logger", key: "logger", width: 220, render: (l: string | null) => l ?? "—" },
    {
      title: "Message",
      dataIndex: "message",
      key: "message",
      render: (msg: string) => <span style={{ fontFamily: "monospace", whiteSpace: "pre-wrap" }}>{msg}</span>,
    },
  ];

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card size="small">
        <Flex gap="small" wrap align="center">
          <Select value={minLevel} onChange={setMinLevel} options={LEVEL_OPTIONS} style={{ minWidth: 160 }} aria-label="Minimum level" />
          <Select value={lines} onChange={setLines} options={LINES_OPTIONS.map((n) => ({ value: n, label: `${n} lines` }))} style={{ minWidth: 140 }} aria-label="Tail length" />
          <Button onClick={load} loading={loading}>
            Refresh
          </Button>
        </Flex>
      </Card>
      <Card size="small">
        <Table<LogEntry>
          size="small"
          rowKey={(_row, index) => index ?? 0}
          loading={loading}
          dataSource={entries}
          columns={columns}
          pagination={false}
          locale={{ emptyText: <Empty description="No log entries" /> }}
        />
      </Card>
    </Space>
  );
}
