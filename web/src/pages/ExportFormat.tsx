import { App, Button, Card, Form, Input, Space, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";

import { ApiRequestError, api, isLicenseLapsed, type ExportFormatSettings } from "../api";

const { Text } = Typography;

interface FormValues {
  export_date_format: string;
  export_csv_filename_tmpl: string;
}

/**
 * Export Format (M7 slice 3, issue #30) — the settings the Load Profile CSV
 * auto-export reads: the timestamp token format and the filename template.
 *
 * **A separate page, not another card on Settings.tsx** (D-16, owner
 * ruling): this page owns `export_date_format` and
 * `export_csv_filename_tmpl` only — the auto-save switch and the output
 * folder live on the Load Profile page next to the data they export,
 * because "Save CSV now" belongs beside the table it saves.
 *
 * **The CSV is always kWh/kvarh and never follows the Display unit
 * setting** (ADR 0013) — the note below exists so an operator who knows
 * that switch does not go looking for it here. Putting it on this page
 * rather than beside the kW/W switch is the whole point: the confusion ADR
 * 0013 exists to prevent starts with the two controls sitting next to each
 * other.
 *
 * One `PUT` replaces all four Export Format settings (D-16/D-17), so
 * saving here must carry `export_auto_save_enabled`/`export_output_dir`
 * through unchanged — the last-fetched settings object is what makes that
 * possible without a second round trip.
 */
export function ExportFormat({ role }: { role: "admin" | "user" }) {
  const { message } = App.useApp();
  const [form] = Form.useForm<FormValues>();
  const [settings, setSettings] = useState<ExportFormatSettings | null>(null);
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
      .exportFormatSettings()
      .then((data) => {
        setSettings(data);
        form.setFieldsValue({
          export_date_format: data.export_date_format,
          export_csv_filename_tmpl: data.export_csv_filename_tmpl,
        });
      })
      .catch((err: unknown) => surface(err, "Could not load the Export Format settings."));
    // Loaded once on mount — the form owns edits from then on, the same
    // pattern Billing.tsx's CaptureSettingsCard uses for capture_dir.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onFinish = (values: FormValues) => {
    if (!settings) return;
    setSaving(true);
    api
      .updateExportFormatSettings({ ...settings, ...values })
      .then((data) => {
        setSettings(data);
        form.setFieldsValue({
          export_date_format: data.export_date_format,
          export_csv_filename_tmpl: data.export_csv_filename_tmpl,
        });
        message.success("Export Format settings saved.");
      })
      .catch((err: unknown) => surface(err, "Could not save the Export Format settings."))
      .finally(() => setSaving(false));
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card size="small" title="Export Format">
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Text type="secondary">
            The Load Profile CSV is always exported in kWh/kvarh — it does not follow the Display unit setting on
            the Settings page. The header is written once when a meter's file is created, and rows append to it for
            months, so its unit can never change.
          </Text>
          <Form
            form={form}
            layout="vertical"
            onFinish={onFinish}
            disabled={role !== "admin" || settings === null || saving}
          >
            <Form.Item
              name="export_date_format"
              label="Date/time format"
              extra="Tokens: yyyy, mm (month), dd, HH (hour), MM (minute), SS."
              rules={[{ required: true, whitespace: true, message: "A date/time format is required." }]}
            >
              <Input placeholder="yyyy-mm-dd HH:MM:SS" />
            </Form.Item>
            <Form.Item
              name="export_csv_filename_tmpl"
              label="CSV filename template"
              extra="Tokens: [meter] / [serial] (the meter's serial number), [date] (today's date)."
              rules={[{ required: true, whitespace: true, message: "A filename template is required." }]}
            >
              <Input placeholder="[meter].csv" />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={saving}>
              Save
            </Button>
          </Form>
        </Space>
      </Card>
    </Space>
  );
}
