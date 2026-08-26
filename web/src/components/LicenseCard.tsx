import { CopyOutlined } from "@ant-design/icons";
import { Alert, App, Button, Card, Descriptions, Input, Space, Tag, Typography } from "antd";
import type { DescriptionsItemType } from "antd/es/descriptions";
import dayjs from "dayjs";
import { useState } from "react";

import { ApiRequestError, api, type LicenseStatus } from "../api";
import { FEATURE_LABELS } from "../features";
import { REASON_TEXT } from "../licenseReasons";

const { Paragraph, Text } = Typography;

/** Human names for the license modes; anything else renders as it was issued. */
const MODE_TEXT: Record<string, string> = { offline: "Offline", leased: "Leased" };

/** Why a pasted code was refused, in words a site engineer can act on. */
function rejectionText(reason: string | null): string {
  const known = reason ? REASON_TEXT[reason] : undefined;
  // Deliberately NOT `reasonText()` from the Activation page: both of its
  // fallbacks say "This machine is in Limited Mode", which is false here —
  // this machine is active and stays active when a code is refused.
  return known ?? "That Activation Code was not accepted.";
}

/**
 * License card on Settings — replacing a license that still works.
 *
 * The Activation page (`pages/Activation.tsx`) is a **gate**: `App.tsx` renders
 * it only while `state !== "active"`, so a machine with a working license had
 * nowhere to paste a new code, and renewing, upgrading or adding meters meant
 * telling a customer to delete `license.lic` by hand. This card is a second
 * entrance; the gate screen is unchanged.
 *
 * **Rejections are handled here, never through `isLicenseLapsed`** — see the
 * catch in `submit()` for why.
 *
 * **The downgrade question, decided: confirm before replacing, then show the
 * result. No pre-flight downgrade detection.** Written down here so it is not
 * "fixed" later:
 *
 * - Nothing on the client can know what a pasted code grants until the server
 *   has verified it, and the only endpoint that verifies is the one that
 *   installs (`POST /api/license/activate`). A real downgrade check would need
 *   a new verify-only endpoint — new admin-gated surface, a new contract — to
 *   answer a question the operator can answer by reading the result. A dry-run
 *   endpoint was **considered and rejected** on those grounds.
 * - `LicenseStatus` carries no feature list at all, so a client-side check
 *   could only compare `max_meters` — and would therefore miss exactly the
 *   accident `docs/issues/010` describes, a typo'd *feature* name that signs
 *   cleanly. **Issue 012 added `enabled_features` and this reasoning still
 *   holds**: that field describes the licence already installed, so it makes
 *   an accidental downgrade *visible after the fact* — which is what the last
 *   bullet asks for — but says nothing about what a code sitting in the
 *   textarea grants. Only installing it can answer that.
 * - What is affordable instead: a `modal.confirm` naming the currently
 *   licensed customer and expiry, so a stray paste onto a working machine
 *   costs a deliberate second click whether or not it is a downgrade; and on
 *   success this same card re-renders with the new license, so an accidental
 *   downgrade is visible within one screen and is undone by pasting the
 *   correct code — with no file deletion, which is the whole point.
 *
 * No ADR: this reverses no recorded decision and creates no cross-module
 * invariant, so it is recorded where this codebase records page-level
 * decisions — the component docstring.
 *
 * Every role sees the card and its values; the code box and the Replace button
 * are disabled for a `user`, the same read/change split as the Display unit
 * card above it. The server-side admin gate on the endpoint is untouched.
 */
export function LicenseCard({
  status,
  role,
  onActivated,
}: {
  status: LicenseStatus;
  role: "admin" | "user";
  onActivated: () => void;
}) {
  const { message, modal } = App.useApp();
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<{ message: string; detail: string } | null>(null);
  const canReplace = role === "admin";

  // Rendered once and reused by both the summary and the confirm dialog, so
  // the two can never disagree about what this machine is licensed to.
  const customerText = status.customer ?? "—";
  const modeText = status.mode ? (MODE_TEXT[status.mode] ?? status.mode) : "—";
  const expiryText = status.expires_at ? dayjs(status.expires_at).format("YYYY-MM-DD HH:mm") : "No expiry";
  const maxMetersText = status.max_meters === null ? "Unlimited" : String(status.max_meters);

  // Issue 012 landed the feature list here, as this comment reserved. It is the
  // **effective** set the server resolved (`.env FEATURES ∩ licence`), not the
  // licence's raw list, so what it shows is exactly what the machine will let
  // you do. This card is also the only place that list is readable — the left
  // nav now hides what is not enabled (D9), so support says "open Settings →
  // License", which is why this card is never itself hidden.
  const items: DescriptionsItemType[] = [
    { key: "customer", label: "Licensed to", children: customerText },
    { key: "mode", label: "Mode", children: modeText },
    { key: "expiry", label: "Expiry", children: expiryText },
    { key: "max_meters", label: "Max meters", children: maxMetersText },
    {
      key: "enabled_features",
      label: "Enabled features",
      children: status.enabled_features.length ? (
        <Space size={[4, 4]} wrap>
          {status.enabled_features.map((key) => (
            <Tag key={key} style={{ marginInlineEnd: 0 }}>
              {FEATURE_LABELS[key] ?? key}
            </Tag>
          ))}
        </Space>
      ) : (
        "None"
      ),
    },
  ];

  const copyMachineId = async () => {
    try {
      await navigator.clipboard.writeText(status.machine_id);
      message.success("Machine ID copied");
    } catch {
      message.warning("Could not copy automatically — select the ID and copy it manually.");
    }
  };

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await api.activate(code.trim());
      setCode("");
      message.success("License replaced. It applies immediately — no restart.");
      onActivated();
    } catch (err) {
      // `isLicenseLapsed` (and so `Settings.tsx`'s `surface()`) is deliberately
      // NOT used here: a refused Activation Code comes back with the very same
      // `LICENSE_INVALID` code a lapsed license produces, so routing it there
      // would reload the whole app on every mistyped code and drop the operator
      // back on Devices with no explanation — leaving them wondering whether
      // they had just broken a working machine. A rejection changes nothing, so
      // it stays on this card and says so.
      setError(
        err instanceof ApiRequestError
          ? {
              message: rejectionText(err.reason),
              detail: `The license on this machine is unchanged — still ${customerText}, expiry ${expiryText}. Nothing was replaced and nothing was written. Check the code and paste it again.`,
            }
          : { message: "Could not reach the server. Is it running?", detail: "" },
      );
    } finally {
      setSubmitting(false);
    }
  };

  const replace = () => {
    if (!code.trim()) {
      setError({ message: "Paste the Activation Code first.", detail: "" });
      return;
    }
    modal.confirm({
      title: "Replace this machine's license?",
      content: `Licensed to: ${customerText} · Mode: ${modeText} · Expiry: ${expiryText} · Max meters: ${maxMetersText}. The pasted code replaces that license immediately, even if it licenses less. Nothing can check what a code grants until it is installed, so make sure it is the right one.`,
      okText: "Replace license",
      onOk: submit,
    });
  };

  return (
    <Card size="small" title="License">
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Descriptions column={1} size="small" items={items} />

        {canReplace ? null : (
          <Alert
            type="info"
            showIcon
            message="An administrator must replace the license"
            description="Send the Machine ID below to your vendor, then ask an administrator to sign in and enter the code."
          />
        )}

        <div>
          <Text strong>Machine ID</Text>
          <Space.Compact style={{ width: "100%", marginTop: 8 }}>
            <Input readOnly value={status.machine_id} style={{ fontFamily: "monospace" }} />
            <Button icon={<CopyOutlined />} onClick={() => void copyMachineId()}>
              Copy
            </Button>
          </Space.Compact>
          <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }}>
            This identifies this computer. Every license is bound to it — send it to your vendor to get a new
            code.
          </Paragraph>
        </div>

        <div>
          <Text strong>New Activation Code</Text>
          <Input.TextArea
            rows={4}
            value={code}
            disabled={!canReplace || submitting}
            onChange={(event) => setCode(event.target.value)}
            placeholder="Paste the single-line Activation Code here"
            style={{ marginTop: 8, fontFamily: "monospace", fontSize: 12 }}
          />
        </div>

        {error ? (
          <Alert type="error" showIcon message={error.message} description={error.detail || undefined} />
        ) : null}

        <Button type="primary" disabled={!canReplace || submitting} loading={submitting} onClick={replace}>
          Replace license
        </Button>
      </Space>
    </Card>
  );
}
