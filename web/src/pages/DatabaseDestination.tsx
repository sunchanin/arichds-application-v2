import { Alert, App, Button, Card, Descriptions, Form, Input, Space, Typography } from "antd";
import type { DescriptionsItemType } from "antd/es/descriptions";
import { useCallback, useEffect, useState } from "react";

import {
  ApiRequestError,
  api,
  isLicenseLapsed,
  type DatabaseDestinationSettings,
  type DatabaseDestinationTest,
  type DatabaseDestinationUpdate,
} from "../api";

const { Text } = Typography;

interface FormValues {
  host: string;
  port: string;
  database: string;
  user: string;
  password: string;
}

/**
 * Database Destination (issue #37 as a shell, wired up by issue #46) — the
 * customer's own MariaDB/MySQL as a Data-out Destination (CONTEXT.md, ADR
 * 0016).
 *
 * **The first paragraph's framing is required wording, not decoration.** ADR
 * 0016's Consequences block calls for it because *"a form that reads like v1's
 * connection settings will be understood as v1's connection settings"* —
 * ARICHDS pushes finished data *to* this database and never runs on it, and
 * keeps reading meters into its own store whether or not the destination is
 * reachable.
 *
 * The shell's second paragraph — the one that said nothing typed here reached
 * a transport — is gone: there is a transport behind the page now, and leaving
 * that sentence would make the page lie in the other direction.
 *
 * No `role` prop is threaded in — `App.tsx` already redirects non-admins away
 * from `database-destination` before this renders.
 */
export function DatabaseDestination() {
  const { message } = App.useApp();
  const [form] = Form.useForm<FormValues>();
  const [settings, setSettings] = useState<DatabaseDestinationSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<DatabaseDestinationTest | null>(null);
  // Whether the form holds edits that are not saved yet. **Test connection
  // deliberately tests the *saved* settings** — a button that tested whatever
  // happens to be typed in the boxes would prove nothing about what the sync
  // will do at the next tick. That is right, and it is also a trap: the
  // natural operator sequence is to fill the form in and press Test before
  // Save. This flag is what makes the difference visible instead of leaving
  // the operator to infer it from a result about settings they have replaced.
  const [dirty, setDirty] = useState(false);

  const surface = useCallback(
    (err: unknown, fallback: string) => {
      if (isLicenseLapsed(err)) {
        window.location.reload();
        return;
      }
      message.error(err instanceof ApiRequestError ? err.message : fallback);
    },
    [message],
  );

  const apply = useCallback(
    (data: DatabaseDestinationSettings) => {
      setSettings(data);
      form.setFieldsValue({
        host: data.host,
        port: String(data.port),
        database: data.database,
        user: data.user,
        password: "",
      });
      // The password box is empty on purpose and must not read as "cleared":
      // resetting its touched flag is what keeps a save that follows a load
      // from sending `password: ""` and wiping the stored one.
      form.resetFields(["password"]);
      form.setFieldValue("password", "");
      // What is on screen now *is* what is saved.
      setDirty(false);
    },
    [form],
  );

  const load = useCallback(() => {
    api
      .databaseDestinationSettings()
      .then(apply)
      .catch((err: unknown) => surface(err, "Could not load the Database Destination settings."));
  }, [apply, surface]);

  useEffect(() => {
    load();
    // Loaded once on mount — the form owns edits from then on, and the status
    // card is refreshed by its own button. **No polling timer**: a
    // fifteen-minute cadence does not warrant one.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onFinish = (values: FormValues) => {
    const body: DatabaseDestinationUpdate = {
      host: values.host?.trim() ?? "",
      port: Number(values.port),
      database: values.database?.trim() ?? "",
      user: values.user?.trim() ?? "",
    };
    // Sent **only when the field was actually edited**. An untouched form
    // therefore cannot clear a stored password, while a deliberately emptied
    // box does store an empty one — which the reference XAMPP `root` account
    // genuinely needs.
    if (form.isFieldTouched("password")) {
      body.password = values.password ?? "";
    }

    setSaving(true);
    api
      .updateDatabaseDestinationSettings(body)
      .then((data) => {
        apply(data);
        setTestResult(null);
        message.success("Database Destination settings saved.");
      })
      .catch((err: unknown) => surface(err, "Could not save the Database Destination settings."))
      .finally(() => setSaving(false));
  };

  const onTest = () => {
    setTesting(true);
    api
      .testDatabaseDestination()
      .then((result) => {
        setTestResult(result);
        if (result.result === "ok") message.success("Connected.");
      })
      .catch((err: unknown) => surface(err, "Could not run the connection test."))
      .finally(() => setTesting(false));
  };

  const lastSync = settings?.last_sync ?? null;

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <div style={{ position: "sticky", top: 0, zIndex: 1 }}>
        <Alert
          type="info"
          showIcon
          title="ARICHDS writes to this database"
          description={
            <p style={{ margin: 0 }}>
              ARICHDS pushes finished data <strong>to</strong> this database. It does not run on it — ARICHDS
              always keeps its own local store and keeps reading meters whether or not this destination is
              reachable.
            </p>
          }
        />
      </div>

      <Card size="small" title="Database Destination">
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Text type="secondary">
            ARICHDS creates and owns two tables here — Load Profile and Billing — and is their only writer. Ask
            for a database dedicated to ARICHDS rather than one holding the customer&rsquo;s own tables: the
            account needs SELECT, INSERT, DELETE, CREATE and ALTER on it.
          </Text>
          <Form
            form={form}
            layout="vertical"
            onFinish={onFinish}
            onValuesChange={() => {
              setDirty(true);
              // A result about the previous settings must not sit under a form
              // that has since been edited.
              setTestResult(null);
            }}
            disabled={settings === null || saving}
          >
            <Form.Item
              name="host"
              label="Host"
              rules={[{ required: true, whitespace: true, message: "A host is required." }]}
            >
              <Input placeholder="127.0.0.1" />
            </Form.Item>
            <Form.Item
              name="port"
              label="Port"
              rules={[
                { required: true, message: "A port is required." },
                {
                  validator: (_rule, value: string) => {
                    const port = Number(value);
                    return Number.isInteger(port) && port >= 1 && port <= 65535
                      ? Promise.resolve()
                      : Promise.reject(new Error("The port must be a whole number between 1 and 65535."));
                  },
                },
              ]}
            >
              <Input inputMode="numeric" placeholder="3306" />
            </Form.Item>
            <Form.Item
              name="database"
              label="Database"
              rules={[{ required: true, whitespace: true, message: "A database name is required." }]}
            >
              <Input placeholder="arichds_dest" />
            </Form.Item>
            <Form.Item name="user" label="User">
              <Input autoComplete="off" />
            </Form.Item>
            <Form.Item
              name="password"
              label="Password"
              extra={
                settings?.password_set
                  ? "A password is saved. Leave this box alone to keep it, or clear it and save to store an empty password."
                  : "No password is saved. Leave this empty if the account has none."
              }
            >
              <Input.Password
                autoComplete="off"
                placeholder={settings?.password_set ? "Unchanged" : ""}
              />
            </Form.Item>
            <Space direction="vertical" size="small" style={{ width: "100%" }}>
              <Space>
                <Button type="primary" htmlType="submit" loading={saving}>
                  Save
                </Button>
                <Button onClick={onTest} loading={testing} disabled={settings === null || saving || dirty}>
                  Test saved connection
                </Button>
              </Space>
              {dirty && (
                <Text type="warning">
                  You have unsaved changes. Test saved connection checks the settings that are saved — the ones
                  the sync will use — so save first, then test.
                </Text>
              )}
            </Space>
          </Form>

          {testResult !== null && (
            <Alert
              type={testResult.result === "ok" ? "success" : "error"}
              showIcon
              title={TEST_TITLES[testResult.result]}
              description={testResult.message}
            />
          )}
        </Space>
      </Card>

      <Card
        size="small"
        title="Last sync"
        extra={
          <Button size="small" onClick={load}>
            Refresh
          </Button>
        }
      >
        <Space direction="vertical" size="small" style={{ width: "100%" }}>
          {lastSync === null ? (
            <Text type="secondary">
              No sync has run since ARICHDS last started. The sync runs every fifteen minutes once a host and a
              database are saved.
            </Text>
          ) : (
            <>
              <Descriptions
                size="small"
                column={1}
                bordered
                items={
                  [
                    { key: "ran_at", label: "Ran at", children: new Date(lastSync.ran_at).toLocaleString() },
                    { key: "lp", label: "Load Profile rows sent", children: lastSync.load_profile_rows },
                    { key: "billing", label: "Billing rows replaced", children: lastSync.billing_rows },
                    { key: "purged", label: "Rows purged past the window", children: lastSync.purged_rows },
                    { key: "skipped", label: "Rows skipped (no meter serial)", children: lastSync.skipped_rows },
                    { key: "took", label: "Took", children: `${lastSync.duration_sec.toFixed(2)} s` },
                  ] satisfies DescriptionsItemType[]
                }
              />
              {lastSync.error !== null && (
                <Alert type="error" showIcon title="The last sync failed" description={lastSync.error} />
              )}
              {lastSync.error === null && lastSync.budget_exhausted && (
                <Alert
                  type="info"
                  showIcon
                  title="The last sync ran out of time and will continue"
                  description="A cycle has a fixed time budget so it can never hold up meter reads. It stopped cleanly and picks up where it left off on the next run — nothing was lost."
                />
              )}
            </>
          )}
          <Text type="secondary">
            This database holds the same 90 days ARICHDS holds, so old rows are deleted from it as well as
            written to it. Its row counts will not match ARICHDS&rsquo;s exactly: this database is trimmed on
            every sync while ARICHDS trims its own store once a day, so the destination can run up to a day
            ahead. That difference is expected and is not a fault.
          </Text>
        </Space>
      </Card>
    </Space>
  );
}

/** A short heading per outcome; the sentence itself comes from the server. */
const TEST_TITLES: Record<DatabaseDestinationTest["result"], string> = {
  ok: "Connected",
  not_configured: "Nothing saved to test yet",
  unreachable: "Could not reach the server",
  auth_failed: "The server refused the user name or password",
  database_missing: "That database does not exist",
  missing_privilege: "Connected, but some privileges could not be confirmed",
};
