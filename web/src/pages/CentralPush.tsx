import { Alert, App, Button, Card, Collapse, Descriptions, Form, Input, Space, Table, Tag, Typography } from "antd";
import type { DescriptionsItemType } from "antd/es/descriptions";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useState } from "react";

import {
  ApiRequestError,
  api,
  isLicenseLapsed,
  type CentralPushContract,
  type CentralPushContractField,
  type CentralPushSettings,
  type CentralPushUpdate,
} from "../api";

const { Text, Paragraph } = Typography;

interface FormValues {
  url: string;
  token: string;
}

const FIELD_COLUMNS: ColumnsType<CentralPushContractField> = [
  { title: "Field", dataIndex: "name", key: "name", width: 260, render: (value: string) => <Text code>{value}</Text> },
  { title: "Type", dataIndex: "type", key: "type", width: 160 },
  { title: "Description", dataIndex: "description", key: "description" },
];

/**
 * API page (ADR 0024, ticket 07) — the Central Push configuration, the last
 * cycle's status, and a read-only view of the published contract.
 *
 * Admin only — `App.tsx` already redirects a `user` away from `central-push`
 * before this renders, the same guard `DatabaseDestination`/`FileUploadDestination`
 * get. Unlike those two this page carries **no licence feature key at all**
 * (ADR 0024): the Central Push is a free capability, so it is visible on
 * every activated machine.
 *
 * Ticket 07 lands no push cycle — `last_cycle` reads `null` until ticket 08's
 * scheduler job starts writing it, and this page renders that quietly rather
 * than as an error, the same way `DatabaseDestination`'s "Last sync" card
 * treats a fresh install.
 */
export function CentralPush() {
  const { message } = App.useApp();
  const [form] = Form.useForm<FormValues>();
  const [settings, setSettings] = useState<CentralPushSettings | null>(null);
  const [contract, setContract] = useState<CentralPushContract | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

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
    (data: CentralPushSettings) => {
      setSettings(data);
      form.setFieldsValue({ url: data.url, token: "" });
      // The token box is empty on purpose and must not read as "cleared":
      // resetting its touched flag keeps a save that follows a load from
      // sending `token: ""` and wiping a stored one — the same shape
      // `DatabaseDestination`'s password field uses.
      form.resetFields(["token"]);
      form.setFieldValue("token", "");
    },
    [form],
  );

  const load = useCallback(() => {
    api
      .centralPushSettings()
      .then(apply)
      .catch((err: unknown) => surface(err, "Could not load the Central Push settings."));
  }, [apply, surface]);

  useEffect(() => {
    load();
    api
      .centralPushContract()
      .then(setContract)
      .catch((err: unknown) => surface(err, "Could not load the published contract."));
    // Loaded once on mount, same as `DatabaseDestination` — no polling timer
    // for a fifteen-minute cadence.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onFinish = (values: FormValues) => {
    const body: CentralPushUpdate = { url: values.url?.trim() ?? "" };
    // Sent only when the field was actually edited — an untouched form
    // cannot clear a stored token, while a deliberately emptied box does
    // clear it.
    if (form.isFieldTouched("token")) {
      body.token = values.token ?? "";
    }

    setSaving(true);
    setSaveError(null);
    api
      .updateCentralPushSettings(body)
      .then((data) => {
        apply(data);
        message.success("Central Push settings saved.");
      })
      .catch((err: unknown) => {
        if (isLicenseLapsed(err)) {
          window.location.reload();
          return;
        }
        // A rejected token names which check failed (ADR 0024) — that is
        // `err.message` on an `ApiRequestError`, not a generic toast.
        setSaveError(err instanceof ApiRequestError ? err.message : "Could not save the Central Push settings.");
      })
      .finally(() => setSaving(false));
  };

  const lastCycle = settings?.last_cycle ?? null;

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card size="small" title="Central Push">
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Text type="secondary">
            Sends Billing, Load Profile, the Energy Summary and the meter roster to the team&rsquo;s own server
            every cycle. Leave the URL empty to send nothing.
          </Text>
          <Form
            form={form}
            layout="vertical"
            onFinish={onFinish}
            onValuesChange={() => setSaveError(null)}
            disabled={settings === null || saving}
          >
            <Form.Item name="url" label="Server URL">
              <Input placeholder="https://push.example.com" />
            </Form.Item>
            <Form.Item
              name="token"
              label="Push Token"
              extra={
                settings?.token_set
                  ? "A token is saved. Leave this box alone to keep it, or clear it and save to remove it."
                  : "No token is saved."
              }
            >
              <Input.Password autoComplete="off" placeholder={settings?.token_set ? "Unchanged" : "Paste the Push Token"} />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={saving}>
              Save
            </Button>
          </Form>

          {saveError !== null && (
            <Alert type="error" showIcon title="Could not save the Central Push settings" description={saveError} />
          )}
        </Space>
      </Card>

      <Card
        size="small"
        title="Last cycle"
        extra={
          <Button size="small" onClick={load}>
            Refresh
          </Button>
        }
      >
        {lastCycle === null ? (
          <Text type="secondary">
            No cycle has run since ARICHDS last started. The push runs every fifteen minutes once a server URL
            and a token are saved.
          </Text>
        ) : (
          <Space direction="vertical" size="small" style={{ width: "100%" }}>
            <Descriptions
              size="small"
              column={1}
              bordered
              items={
                [
                  { key: "ran_at", label: "Ran at", children: new Date(lastCycle.ran_at).toLocaleString() },
                  { key: "outcome", label: "Outcome", children: lastCycle.outcome },
                  { key: "meters", label: "Meters sent", children: lastCycle.meters_rows },
                  { key: "billing", label: "Billing rows sent", children: lastCycle.billing_rows },
                  { key: "energy", label: "Energy Summary rows sent", children: lastCycle.energy_summary_rows },
                  { key: "lp", label: "Load Profile rows sent", children: lastCycle.load_profile_rows },
                  { key: "skipped", label: "Rows skipped (no meter serial)", children: lastCycle.skipped_rows },
                  { key: "took", label: "Took", children: `${lastCycle.duration_sec.toFixed(2)} s` },
                ] satisfies DescriptionsItemType[]
              }
            />
            {lastCycle.error !== null && (
              <Alert type="error" showIcon title="The last cycle failed" description={lastCycle.error} />
            )}
          </Space>
        )}
      </Card>

      <Card size="small" title="Published contract" extra={contract && <Tag color="blue">version {contract.contract_version}</Tag>}>
        {contract === null ? (
          <Text type="secondary">Loading…</Text>
        ) : (
          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            <Paragraph type="secondary" style={{ marginBottom: 0 }}>
              Give this to the team building the receiving server. It is generated from the same payload models
              the machine uses to build what it sends, so it cannot drift from what is actually pushed.
            </Paragraph>
            <Descriptions
              size="small"
              column={1}
              bordered
              items={
                [
                  { key: "holdings", label: "Holdings", children: <Text code>{contract.holdings_endpoint}</Text> },
                  { key: "push", label: "Push", children: <Text code>{contract.push_endpoint}</Text> },
                ] satisfies DescriptionsItemType[]
              }
            />
            <Collapse
              items={[
                {
                  key: "__envelope",
                  label: (
                    <Space>
                      <Text strong>Push envelope</Text>
                      <Tag>{contract.push_endpoint}</Tag>
                    </Space>
                  ),
                  children: (
                    <Table
                      size="small"
                      rowKey="name"
                      pagination={false}
                      dataSource={contract.envelope}
                      columns={FIELD_COLUMNS}
                    />
                  ),
                },
                {
                  key: "__holdings",
                  label: (
                    <Space>
                      <Text strong>Holdings response</Text>
                      <Tag>{contract.holdings_endpoint}</Tag>
                    </Space>
                  ),
                  children: (
                    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                      <Table
                        size="small"
                        rowKey="name"
                        pagination={false}
                        dataSource={contract.holdings}
                        columns={FIELD_COLUMNS}
                      />
                      {contract.holdings_entries.map((entry) => (
                        <div key={entry.kind}>
                          <Text strong>{entry.kind.replaceAll("_", " ")}</Text>
                          <Table
                            size="small"
                            rowKey="name"
                            pagination={false}
                            dataSource={entry.fields}
                            columns={FIELD_COLUMNS}
                            style={{ marginTop: 8 }}
                          />
                        </div>
                      ))}
                    </Space>
                  ),
                },
                ...contract.kinds.map((kind) => ({
                  key: kind.kind,
                  label: (
                    <Space>
                      <Text strong>{kind.kind}</Text>
                      <Tag>{kind.replace_whole_roster ? "full replace every cycle" : `key: ${kind.natural_key.join(", ")}`}</Tag>
                    </Space>
                  ),
                  children: (
                    <Table
                      size="small"
                      rowKey="name"
                      pagination={false}
                      dataSource={kind.fields}
                      columns={FIELD_COLUMNS}
                    />
                  ),
                })),
              ]}
            />
            <div>
              <Text strong>Notes</Text>
              <ul style={{ marginTop: 8, marginBottom: 0 }}>
                {contract.notes.map((note) => (
                  <li key={note}>
                    <Text type="secondary">{note}</Text>
                  </li>
                ))}
              </ul>
            </div>
          </Space>
        )}
      </Card>
    </Space>
  );
}
