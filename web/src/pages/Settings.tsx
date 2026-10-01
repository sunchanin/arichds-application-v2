import { App, Card, Segmented, Space, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";

import { ApiRequestError, api, isLicenseLapsed, type DisplayUnitScale, type LicenseStatus } from "../api";
import { LicenseCard } from "../components/LicenseCard";

const { Text } = Typography;

const OPTIONS: { label: string; value: DisplayUnitScale }[] = [
  { label: "Kilo (kW, kWh)", value: "kilo" },
  { label: "Base (W, Wh)", value: "base" },
];

/**
 * Settings — the machine-wide settings page. Two cards today:
 *
 * 1. **Display unit** — kW/kWh vs W/Wh (a CR, not part of any milestone's
 *    original shape).
 * 2. **License** (`components/LicenseCard.tsx`, issue 011) — what this machine
 *    is licensed to, and the only place a license that *still works* can be
 *    replaced. The Activation page is a gate `App.tsx` stops rendering the
 *    moment the machine is active, so without this card renewing a lease meant
 *    deleting `license.lic` by hand.
 *
 * Both follow the same read/change split: **one value for the whole machine,
 * not per user** (owner ruling), every authenticated role sees the page and
 * its current values, and the controls are disabled for a `user` — matching
 * each backend's own admin-only write, the same split `Billing.tsx`'s
 * `capture_dir` form already uses.
 *
 * The display-unit setting **never changes the database or an API payload** —
 * it only decides how a value is rendered, on the Billing, Load Profile and
 * capture PDF/xlsx output (`web/src/units.ts` does the actual conversion, on
 * the Billing and Load Profile pages). Every readings endpoint keeps returning
 * kWh/kvarh/kW/kvar regardless of this setting.
 */
export function Settings({
  role,
  status,
  onActivated,
}: {
  role: "admin" | "user";
  status: LicenseStatus;
  onActivated: () => void;
}) {
  const { message } = App.useApp();
  const [scale, setScale] = useState<DisplayUnitScale | null>(null);
  const [saving, setSaving] = useState(false);

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

  useEffect(() => {
    api
      .displaySettings()
      .then((data) => setScale(data.display_unit_scale))
      .catch((err: unknown) => surface(err, "Could not load the display unit setting."));
  }, [surface]);

  const onChange = (value: DisplayUnitScale) => {
    setSaving(true);
    api
      .updateDisplaySettings(value)
      .then((data) => {
        setScale(data.display_unit_scale);
        message.success("Display unit saved.");
      })
      .catch((err: unknown) => surface(err, "Could not save the display unit setting."))
      .finally(() => setSaving(false));
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card size="small" title="Display unit">
        <Space direction="vertical" size="small">
          <Text type="secondary">
            Applies machine-wide, to the Billing and Load Profile pages and the capture PDF/xlsx files.
          </Text>
          <Segmented<DisplayUnitScale>
            value={scale ?? "kilo"}
            options={OPTIONS}
            disabled={role !== "admin" || scale === null || saving}
            onChange={onChange}
          />
        </Space>
      </Card>

      <LicenseCard status={status} role={role} onActivated={onActivated} />
    </Space>
  );
}
