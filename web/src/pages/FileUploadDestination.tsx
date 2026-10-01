import { Alert, App, Button, Card, Descriptions, Form, Input, Space, Tabs, Tag, Typography } from "antd";
import type { DescriptionsItemType } from "antd/es/descriptions";
import { useCallback, useEffect, useState } from "react";

import {
  ApiRequestError,
  api,
  isLicenseLapsed,
  type FileUploadFtpsTest,
  type FileUploadFtpsUpdate,
  type FileUploadHttpsTest,
  type FileUploadHttpsUpdate,
  type FileUploadSettings,
  type FileUploadSftpTest,
  type FileUploadSftpUpdate,
} from "../api";

const { Text, Paragraph } = Typography;

type Protocol = "sftp" | "ftps" | "https";

interface SftpFormValues {
  host: string;
  port: string;
  username: string;
  password: string;
  key_path: string;
  key_passphrase: string;
  remote_root: string;
}

interface FtpsFormValues {
  host: string;
  port: string;
  username: string;
  password: string;
  remote_root: string;
}

interface HttpsFormValues {
  url: string;
  token: string;
  remote_root: string;
}

const PROTOCOL_LABELS: Record<Protocol, string> = { sftp: "SFTP", ftps: "FTPS", https: "HTTPS" };

function TabLabel({ protocol, active }: { protocol: Protocol; active: boolean }) {
  return (
    <Space size="small">
      {PROTOCOL_LABELS[protocol]}
      {active && (
        <Tag color="green" style={{ marginInlineEnd: 0 }}>
          Active
        </Tag>
      )}
    </Space>
  );
}

/** What every tab's server side needs to know, and what this machine will never do — shared verbatim across tabs
 * (SPEC story 23) so the three cannot drift apart in wording. */
function HowTo({ prerequisites }: { prerequisites: string[] }) {
  return (
    <Space direction="vertical" size="small" style={{ width: "100%" }}>
      <div>
        <Text strong>Before you save</Text>
        <ul style={{ marginTop: 4, marginBottom: 0 }}>
          {prerequisites.map((item) => (
            <li key={item}>
              <Text type="secondary">{item}</Text>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <Text strong>What this machine will create</Text>
        <ul style={{ marginTop: 4, marginBottom: 0 }}>
          <li>
            <Text type="secondary">
              <Text code>export/</Text> under the remote root, holding the same export files this machine keeps
            </Text>
          </li>
          <li>
            <Text type="secondary">
              <Text code>captures/&lt;Meter Serial&gt;/</Text> under the remote root, holding the Billing capture
              documents
            </Text>
          </li>
          <li>
            <Text type="secondary">
              <Text code>arichds-manifest.json</Text> at the remote root — a plain-JSON inventory of what has
              arrived, readable without this software
            </Text>
          </li>
        </ul>
      </div>
      <div>
        <Text strong>Not supported</Text>
        <ul style={{ marginTop: 4, marginBottom: 0 }}>
          <li>
            <Text type="secondary">Plain FTP — there is no such protocol choice on this page</Text>
          </li>
          <li>
            <Text type="secondary">Implicit FTPS (port 990) — only explicit TLS on the standard port</Text>
          </li>
          <li>
            <Text type="secondary">A self-signed certificate — the connection is refused, not trusted</Text>
          </li>
          <li>
            <Text type="secondary">Deleting anything on the server — this machine only adds and replaces</Text>
          </li>
        </ul>
      </div>
    </Space>
  );
}

/**
 * File Upload Destination (SPEC §3.8, ADR 0025, tickets 01-05) — menu label
 * **FTP** (CONTEXT.md's glossary term stays *File Upload Destination*; the
 * two disagree on purpose, ADR 0025 decision 1).
 *
 * Three tabs, one active protocol — the tab saved last. All three real
 * transports (SFTP, ticket 04; FTPS, ticket 05; HTTPS, ticket 03) move real
 * bytes today, on the cycle ticket 02 landed and on the **Upload now**
 * button below.
 *
 * No `role` prop threaded in — `App.tsx` already redirects non-admins away
 * from `file-upload-destination` before this renders, the same guard
 * `DatabaseDestination`/`CentralPush` get.
 */
export function FileUploadDestination() {
  const { message } = App.useApp();
  const [sftpForm] = Form.useForm<SftpFormValues>();
  const [ftpsForm] = Form.useForm<FtpsFormValues>();
  const [httpsForm] = Form.useForm<HttpsFormValues>();

  const [settings, setSettings] = useState<FileUploadSettings | null>(null);
  const [activeTab, setActiveTab] = useState<Protocol>("sftp");
  const [savingSftp, setSavingSftp] = useState(false);
  const [savingFtps, setSavingFtps] = useState(false);
  const [savingHttps, setSavingHttps] = useState(false);
  const [uploadingNow, setUploadingNow] = useState(false);
  const [sftpError, setSftpError] = useState<string | null>(null);
  const [ftpsError, setFtpsError] = useState<string | null>(null);
  const [httpsError, setHttpsError] = useState<string | null>(null);
  const [testingHttps, setTestingHttps] = useState(false);
  const [httpsTestResult, setHttpsTestResult] = useState<FileUploadHttpsTest | null>(null);
  const [testingSftp, setTestingSftp] = useState(false);
  const [sftpTestResult, setSftpTestResult] = useState<FileUploadSftpTest | null>(null);
  const [pinningSftpHostKey, setPinningSftpHostKey] = useState(false);
  const [testingFtps, setTestingFtps] = useState(false);
  const [ftpsTestResult, setFtpsTestResult] = useState<FileUploadFtpsTest | null>(null);

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
    (data: FileUploadSettings, firstLoad: boolean) => {
      setSettings(data);
      if (firstLoad && (data.active_protocol === "sftp" || data.active_protocol === "ftps" || data.active_protocol === "https")) {
        setActiveTab(data.active_protocol);
      }

      sftpForm.setFieldsValue({
        host: data.sftp.host,
        port: String(data.sftp.port),
        username: data.sftp.username,
        password: "",
        key_path: data.sftp.key_path,
        key_passphrase: "",
        remote_root: data.sftp.remote_root,
      });
      sftpForm.resetFields(["password", "key_passphrase"]);
      sftpForm.setFieldValue("password", "");
      sftpForm.setFieldValue("key_passphrase", "");

      ftpsForm.setFieldsValue({
        host: data.ftps.host,
        port: String(data.ftps.port),
        username: data.ftps.username,
        password: "",
        remote_root: data.ftps.remote_root,
      });
      ftpsForm.resetFields(["password"]);
      ftpsForm.setFieldValue("password", "");

      httpsForm.setFieldsValue({ url: data.https.url, token: "", remote_root: data.https.remote_root });
      httpsForm.resetFields(["token"]);
      httpsForm.setFieldValue("token", "");
    },
    [sftpForm, ftpsForm, httpsForm],
  );

  const load = useCallback(
    (firstLoad: boolean) => {
      api
        .fileUploadSettings()
        .then((data) => apply(data, firstLoad))
        .catch((err: unknown) => surface(err, "Could not load the File Upload Destination settings."));
    },
    [apply, surface],
  );

  const onUploadNow = useCallback(() => {
    setUploadingNow(true);
    api
      .uploadFileUploadNow()
      .then((result) => {
        setSettings((prev) => (prev === null ? prev : { ...prev, status: result.status }));
        if (result.finished) {
          message.success("Upload cycle finished — see the status below.");
        } else {
          // The one-shot lane runs behind every job already due on the
          // scheduler's one thread — a slow meter read ahead of it can
          // outlast this request's own wait. `result.status` here is
          // whatever was already published, not this cycle's own result,
          // so it must not be shown as success (reviewer finding, ticket
          // 02 round 1, problem 2).
          message.info("Still running — press Refresh in a moment.");
        }
      })
      .catch((err: unknown) => surface(err, "Could not run the upload cycle."))
      .finally(() => setUploadingNow(false));
  }, [message, surface]);

  const onTestHttps = useCallback(() => {
    setTestingHttps(true);
    api
      .testFileUploadHttps()
      .then((result) => {
        setHttpsTestResult(result);
        if (result.result === "ok") message.success("Connected.");
      })
      .catch((err: unknown) => surface(err, "Could not run the connection test."))
      .finally(() => setTestingHttps(false));
  }, [message, surface]);

  const onTestSftp = useCallback(() => {
    setTestingSftp(true);
    api
      .testFileUploadSftp()
      .then((result) => {
        setSftpTestResult(result);
        if (result.result === "ok") message.success("Connected.");
      })
      .catch((err: unknown) => surface(err, "Could not run the connection test."))
      .finally(() => setTestingSftp(false));
  }, [message, surface]);

  const onTestFtps = useCallback(() => {
    setTestingFtps(true);
    api
      .testFileUploadFtps()
      .then((result) => {
        setFtpsTestResult(result);
        if (result.result === "ok") message.success("Connected.");
      })
      .catch((err: unknown) => surface(err, "Could not run the connection test."))
      .finally(() => setTestingFtps(false));
  }, [message, surface]);

  const onPinSftpHostKey = useCallback(() => {
    const fingerprint = sftpTestResult?.fingerprint;
    if (!fingerprint) return;
    setPinningSftpHostKey(true);
    api
      .pinFileUploadSftpHostKey({ fingerprint })
      .then((data) => {
        apply(data, false);
        setSftpTestResult(null);
        message.success("Host key pinned.");
      })
      .catch((err: unknown) => surface(err, "Could not pin the host key."))
      .finally(() => setPinningSftpHostKey(false));
  }, [sftpTestResult, apply, message, surface]);

  useEffect(() => {
    load(true);
    // Loaded once on mount, the same as `DatabaseDestination`/`CentralPush` —
    // no polling timer for a fifteen-minute cadence.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onFinishSftp = (values: SftpFormValues) => {
    const body: FileUploadSftpUpdate = {
      host: values.host?.trim() ?? "",
      port: Number(values.port),
      username: values.username?.trim() ?? "",
      key_path: values.key_path?.trim() ?? "",
      remote_root: values.remote_root?.trim() ?? "",
    };
    if (sftpForm.isFieldTouched("password")) body.password = values.password ?? "";
    if (sftpForm.isFieldTouched("key_passphrase")) body.key_passphrase = values.key_passphrase ?? "";

    setSavingSftp(true);
    setSftpError(null);
    api
      .updateFileUploadSftp(body)
      .then((data) => {
        apply(data, false);
        message.success("SFTP settings saved. SFTP is now the active protocol.");
      })
      .catch((err: unknown) => {
        if (isLicenseLapsed(err)) {
          window.location.reload();
          return;
        }
        setSftpError(err instanceof ApiRequestError ? err.message : "Could not save the SFTP settings.");
      })
      .finally(() => setSavingSftp(false));
  };

  const onFinishFtps = (values: FtpsFormValues) => {
    const body: FileUploadFtpsUpdate = {
      host: values.host?.trim() ?? "",
      port: Number(values.port),
      username: values.username?.trim() ?? "",
      remote_root: values.remote_root?.trim() ?? "",
    };
    if (ftpsForm.isFieldTouched("password")) body.password = values.password ?? "";

    setSavingFtps(true);
    setFtpsError(null);
    api
      .updateFileUploadFtps(body)
      .then((data) => {
        apply(data, false);
        setFtpsTestResult(null);
        message.success("FTPS settings saved. FTPS is now the active protocol.");
      })
      .catch((err: unknown) => {
        if (isLicenseLapsed(err)) {
          window.location.reload();
          return;
        }
        setFtpsError(err instanceof ApiRequestError ? err.message : "Could not save the FTPS settings.");
      })
      .finally(() => setSavingFtps(false));
  };

  const onFinishHttps = (values: HttpsFormValues) => {
    const body: FileUploadHttpsUpdate = { url: values.url?.trim() ?? "", remote_root: values.remote_root?.trim() ?? "" };
    if (httpsForm.isFieldTouched("token")) body.token = values.token ?? "";

    setSavingHttps(true);
    setHttpsError(null);
    api
      .updateFileUploadHttps(body)
      .then((data) => {
        apply(data, false);
        setHttpsTestResult(null);
        message.success("HTTPS settings saved. HTTPS is now the active protocol.");
      })
      .catch((err: unknown) => {
        if (isLicenseLapsed(err)) {
          window.location.reload();
          return;
        }
        setHttpsError(err instanceof ApiRequestError ? err.message : "Could not save the HTTPS settings.");
      })
      .finally(() => setSavingHttps(false));
  };

  const portRules = [
    { required: true, message: "A port is required." },
    {
      validator: (_rule: unknown, value: string) => {
        const port = Number(value);
        return Number.isInteger(port) && port >= 1 && port <= 65535
          ? Promise.resolve()
          : Promise.reject(new Error("The port must be a whole number between 1 and 65535."));
      },
    },
  ];

  const status = settings?.status ?? null;

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="FTP"
        description={
          <Text>
            Copies this machine&rsquo;s export files and Billing capture documents to a server of your team&rsquo;s
            choosing, over SFTP, FTPS or HTTPS — one active at a time. <strong>Nothing is sent while this page is
            empty.</strong> To stop uploading later, clear the host (or URL) on the active tab and save — the other
            fields stay, so switching back on is one save.
          </Text>
        }
      />

      <Card size="small" title="File Upload Destination">
        <Tabs
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key as Protocol)}
          items={[
            {
              key: "sftp",
              label: <TabLabel protocol="sftp" active={settings?.active_protocol === "sftp"} />,
              children: (
                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                  <Form
                    form={sftpForm}
                    layout="vertical"
                    onFinish={onFinishSftp}
                    onValuesChange={() => setSftpError(null)}
                    disabled={settings === null || savingSftp}
                  >
                    <Form.Item name="host" label="Host">
                      <Input placeholder="sftp.example.com" />
                    </Form.Item>
                    <Form.Item name="port" label="Port" rules={portRules}>
                      <Input inputMode="numeric" placeholder="22" />
                    </Form.Item>
                    <Form.Item name="username" label="User">
                      <Input autoComplete="off" />
                    </Form.Item>
                    <Form.Item
                      name="password"
                      label="Password"
                      extra={settings?.sftp.password_set ? "A password is set. Leave this box alone to keep it." : "No password is set."}
                    >
                      <Input.Password autoComplete="off" placeholder={settings?.sftp.password_set ? "Unchanged" : ""} />
                    </Form.Item>
                    <Form.Item name="key_path" label="Key file path" extra="A private-key file's path on this machine (RSA or Ed25519). Provide a password, a key file path, or both — the key file is used when both are set.">
                      <Input placeholder="C:\path\to\id_ed25519" />
                    </Form.Item>
                    <Form.Item
                      name="key_passphrase"
                      label="Key file passphrase"
                      extra={
                        settings?.sftp.key_passphrase_set
                          ? "A passphrase is set. Leave this box alone to keep it."
                          : "No passphrase is set. Leave empty if the key file has none."
                      }
                    >
                      <Input.Password autoComplete="off" placeholder={settings?.sftp.key_passphrase_set ? "Unchanged" : ""} />
                    </Form.Item>
                    <Form.Item name="remote_root" label="Remote root">
                      <Input placeholder="/home/arichds" />
                    </Form.Item>
                    <Form.Item label="Host key">
                      {settings?.sftp.host_key_fingerprint ? (
                        <Text code>Pinned: {settings.sftp.host_key_fingerprint}</Text>
                      ) : (
                        <Text type="secondary">
                          Not pinned yet — save the tab, then press Test saved connection to see the server&rsquo;s key.
                        </Text>
                      )}
                    </Form.Item>
                    <Space>
                      <Button type="primary" htmlType="submit" loading={savingSftp}>
                        Save
                      </Button>
                      <Button loading={testingSftp} onClick={onTestSftp}>
                        Test saved connection
                      </Button>
                    </Space>
                  </Form>
                  {sftpError !== null && <Alert type="error" showIcon title="Could not save the SFTP settings" description={sftpError} />}
                  {sftpTestResult !== null && (
                    <Alert
                      type={sftpTestResult.result === "ok" ? "success" : "warning"}
                      showIcon
                      title={
                        sftpTestResult.result === "ok"
                          ? "Connected"
                          : sftpTestResult.result === "host_key_not_pinned"
                            ? "Host key not pinned"
                            : sftpTestResult.result === "host_key_mismatch"
                              ? "Host key changed"
                              : `Could not connect (${sftpTestResult.result.replaceAll("_", " ")})`
                      }
                      description={
                        <Space direction="vertical" size="small" style={{ width: "100%" }}>
                          <Text>{sftpTestResult.message}</Text>
                          {(sftpTestResult.result === "host_key_not_pinned" ||
                            sftpTestResult.result === "host_key_mismatch") &&
                            sftpTestResult.fingerprint !== null && (
                              <Button size="small" loading={pinningSftpHostKey} onClick={onPinSftpHostKey}>
                                Pin this key
                              </Button>
                            )}
                        </Space>
                      }
                    />
                  )}
                  <HowTo
                    prerequisites={[
                      "An SFTP (SSH) account and its home folder, ready to receive files.",
                      "The SSH port your team's server listens on (usually 22).",
                      "Either a password for that account, or a private-key file placed on this machine — the key file stays on this machine and is never uploaded or stored in the database.",
                    ]}
                  />
                </Space>
              ),
            },
            {
              key: "ftps",
              label: <TabLabel protocol="ftps" active={settings?.active_protocol === "ftps"} />,
              children: (
                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                  <Form
                    form={ftpsForm}
                    layout="vertical"
                    onFinish={onFinishFtps}
                    onValuesChange={() => setFtpsError(null)}
                    disabled={settings === null || savingFtps}
                  >
                    <Form.Item name="host" label="Host">
                      <Input placeholder="ftps.example.com" />
                    </Form.Item>
                    <Form.Item name="port" label="Port" rules={portRules}>
                      <Input inputMode="numeric" placeholder="21" />
                    </Form.Item>
                    <Form.Item name="username" label="User">
                      <Input autoComplete="off" />
                    </Form.Item>
                    <Form.Item
                      name="password"
                      label="Password"
                      extra={settings?.ftps.password_set ? "A password is set. Leave this box alone to keep it." : "No password is set."}
                    >
                      <Input.Password autoComplete="off" placeholder={settings?.ftps.password_set ? "Unchanged" : ""} />
                    </Form.Item>
                    <Form.Item name="remote_root" label="Remote root">
                      <Input placeholder="/home/arichds" />
                    </Form.Item>
                    <Space>
                      <Button type="primary" htmlType="submit" loading={savingFtps}>
                        Save
                      </Button>
                      <Button loading={testingFtps} onClick={onTestFtps}>
                        Test saved connection
                      </Button>
                    </Space>
                  </Form>
                  {ftpsError !== null && <Alert type="error" showIcon title="Could not save the FTPS settings" description={ftpsError} />}
                  {ftpsTestResult !== null && (
                    <Alert
                      type={ftpsTestResult.result === "ok" ? "success" : "warning"}
                      showIcon
                      title={
                        ftpsTestResult.result === "ok"
                          ? "Connected"
                          : `Could not connect (${ftpsTestResult.result.replaceAll("_", " ")})`
                      }
                      description={
                        <Space direction="vertical" size="small" style={{ width: "100%" }}>
                          <Text>{ftpsTestResult.message}</Text>
                          {ftpsTestResult.subject !== null && (
                            <Text type="secondary">
                              Certificate: <Text code>{ftpsTestResult.subject}</Text>
                            </Text>
                          )}
                        </Space>
                      }
                    />
                  )}
                  <HowTo
                    prerequisites={[
                      "An FTP account and its home folder, ready to receive files.",
                      "Explicit FTPS on the standard control port (21) — implicit FTPS on 990 is not offered.",
                      "A certificate this machine's Windows trust store accepts (issued by a trusted authority) — a self-signed certificate is refused, not trusted.",
                    ]}
                  />
                </Space>
              ),
            },
            {
              key: "https",
              label: <TabLabel protocol="https" active={settings?.active_protocol === "https"} />,
              children: (
                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                  <Form
                    form={httpsForm}
                    layout="vertical"
                    onFinish={onFinishHttps}
                    onValuesChange={() => setHttpsError(null)}
                    disabled={settings === null || savingHttps}
                  >
                    <Form.Item name="url" label="Server URL">
                      <Input placeholder="https://files.example.com" />
                    </Form.Item>
                    <Form.Item
                      name="token"
                      label="Token"
                      extra={settings?.https.token_set ? "A token is set. Leave this box alone to keep it." : "No token is set."}
                    >
                      <Input.Password autoComplete="off" placeholder={settings?.https.token_set ? "Unchanged" : "Paste the token"} />
                    </Form.Item>
                    <Form.Item name="remote_root" label="Remote root">
                      <Input placeholder="/arichds" />
                    </Form.Item>
                    <Space>
                      <Button type="primary" htmlType="submit" loading={savingHttps}>
                        Save
                      </Button>
                      <Button loading={testingHttps} onClick={onTestHttps}>
                        Test saved connection
                      </Button>
                    </Space>
                  </Form>
                  {httpsError !== null && <Alert type="error" showIcon title="Could not save the HTTPS settings" description={httpsError} />}
                  {httpsTestResult !== null && (
                    <Alert
                      type={httpsTestResult.result === "ok" ? "success" : "warning"}
                      showIcon
                      title={
                        httpsTestResult.result === "ok"
                          ? "Connected"
                          : `Could not connect (${httpsTestResult.result.replaceAll("_", " ")})`
                      }
                      description={httpsTestResult.message}
                    />
                  )}
                  <HowTo
                    prerequisites={[
                      "A server implementing the three Files endpoints published on the API page: GET .../v1/files/manifest, PUT .../v1/files/{relative path}, PUT .../v1/files/manifest.",
                      "A Bearer token the server will accept — the Push Token can be reused, or issue a different one.",
                      "A certificate issued by a trusted authority — a self-signed certificate is refused.",
                    ]}
                  />
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Card
        size="small"
        title="Last cycle"
        extra={
          <Space size="small">
            <Button size="small" onClick={() => load(false)}>
              Refresh
            </Button>
            <Button size="small" type="primary" loading={uploadingNow} onClick={onUploadNow}>
              Upload now
            </Button>
          </Space>
        }
      >
        {status === null ? (
          <Text type="secondary">
            Not yet run since start. Saving a tab above only stores the configuration — press{" "}
            <Text strong>Upload now</Text> to prove it, or wait for the next scheduled cycle.
          </Text>
        ) : status.outcome === "not_configured" ? (
          <Text type="secondary">
            Nothing was sent — the active tab has no host or URL. Leave it empty to keep uploads off, or fill it in
            and save to start; then press <Text strong>Upload now</Text> or wait for the next scheduled cycle.
          </Text>
        ) : (
          <Space direction="vertical" size="small" style={{ width: "100%" }}>
            <Descriptions
              size="small"
              column={1}
              bordered
              items={
                [
                  { key: "ran_at", label: "Ran at", children: new Date(status.ran_at).toLocaleString() },
                  { key: "protocol", label: "Protocol", children: status.protocol },
                  { key: "outcome", label: "Outcome", children: status.outcome },
                  { key: "files_sent", label: "Files sent", children: status.files_sent },
                  { key: "bytes_sent", label: "Bytes sent", children: status.bytes_sent },
                  { key: "files_skipped_unchanged", label: "Files skipped (unchanged)", children: status.files_skipped_unchanged },
                  { key: "files_skipped_budget", label: "Files skipped (budget)", children: status.files_skipped_budget },
                  {
                    key: "files_skipped_no_serial",
                    label: "Devices skipped (no Meter Serial)",
                    children: status.files_skipped_no_serial,
                  },
                  { key: "took", label: "Took", children: `${status.duration_sec.toFixed(2)} s` },
                ] satisfies DescriptionsItemType[]
              }
            />
            {status.error !== null && <Alert type="error" showIcon title="The last cycle failed" description={status.error} />}
          </Space>
        )}
      </Card>

      <Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Nothing is sent while this page is empty.
      </Paragraph>
    </Space>
  );
}
