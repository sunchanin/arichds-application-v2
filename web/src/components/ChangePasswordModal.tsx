import { App, Form, Input, Modal } from "antd";
import { useState } from "react";

import { ApiRequestError, api } from "../api";

/** Minimum password length, mirroring the API's own rule (SPEC §3.2). */
const MIN_PASSWORD_LENGTH = 8;

interface ChangePasswordForm {
  current: string;
  next: string;
  confirm: string;
}

/**
 * Change your own password — available to every role (M2-2).
 *
 * The server keeps the session that submits this and revokes the user's other
 * ones, so the operator stays signed in here and any other browser they left
 * open is signed out. The success message says so, because "your other sessions
 * ended" is surprising if it is not announced.
 *
 * The confirm field is validated in the browser only and is never sent — the
 * API takes `current_password` and `new_password`, nothing else.
 */
export function ChangePasswordModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { message } = App.useApp();
  const [form] = Form.useForm<ChangePasswordForm>();
  const [submitting, setSubmitting] = useState(false);

  const submit = async (values: ChangePasswordForm) => {
    setSubmitting(true);
    try {
      await api.changeOwnPassword(values.current, values.next);
      message.success("Password changed. Your other sessions have been signed out.");
      form.resetFields();
      onClose();
    } catch (err) {
      message.error(err instanceof ApiRequestError ? err.message : "Could not change the password");
    } finally {
      setSubmitting(false);
    }
  };

  const close = () => {
    form.resetFields();
    onClose();
  };

  return (
    <Modal
      open={open}
      title="Change password"
      okText="Change password"
      confirmLoading={submitting}
      onOk={() => void form.submit()}
      onCancel={close}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" onFinish={(values) => void submit(values)} disabled={submitting}>
        <Form.Item
          name="current"
          label="Current password"
          rules={[{ required: true, message: "Type your current password." }]}
        >
          <Input.Password autoComplete="current-password" />
        </Form.Item>

        <Form.Item
          name="next"
          label="New password"
          rules={[
            { required: true, message: "Choose a new password." },
            { min: MIN_PASSWORD_LENGTH, message: `Use at least ${MIN_PASSWORD_LENGTH} characters.` },
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>

        <Form.Item
          name="confirm"
          label="Confirm new password"
          dependencies={["next"]}
          rules={[
            { required: true, message: "Type the new password again." },
            ({ getFieldValue }) => ({
              validator: (_, value: string) =>
                !value || getFieldValue("next") === value
                  ? Promise.resolve()
                  : Promise.reject(new Error("The two passwords do not match.")),
            }),
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
