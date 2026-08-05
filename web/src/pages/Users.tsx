import { DeleteOutlined, KeyOutlined, UserAddOutlined } from "@ant-design/icons";
import {
  App,
  Button,
  Card,
  Col,
  Form,
  Input,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import { ApiRequestError, api, type NewUser, type User } from "../api";

const { Text, Title } = Typography;

/** Minimum password length, mirroring the API's own rule (SPEC §3.2). */
const MIN_PASSWORD_LENGTH = 8;

/** The two roles, as the `Select` inputs on this page offer them. */
const ROLE_OPTIONS = [
  { value: "user", label: "user" },
  { value: "admin", label: "admin" },
];

interface ResetForm {
  next: string;
  confirm: string;
}

/**
 * User Management (M2-2) — admin-only: `App.tsx` never renders this for a
 * `user`, and every endpoint behind it is admin-only anyway.
 *
 * Controls on **your own row** are disabled: an admin may not delete itself,
 * change its own role, or reset its own password. The disabling is convenience
 * only — the server enforces all three with a 400, and any error it returns is
 * surfaced verbatim, so the page cannot drift into telling a comfortable lie.
 * Your own password is changed from the header instead, where the current one
 * is asked for.
 *
 * Unpaginated on purpose: this box holds a handful of accounts (SPEC §2 —
 * 10–30 meters per site, a couple of operators).
 */
export function Users({ currentUserId }: { currentUserId: number }) {
  const { message } = App.useApp();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetTarget, setResetTarget] = useState<User | null>(null);
  const [form] = Form.useForm<NewUser>();
  const [resetFormInstance] = Form.useForm<ResetForm>();

  const refresh = useCallback(async () => {
    try {
      setUsers(await api.listUsers());
    } catch (err) {
      if (err instanceof ApiRequestError && err.code === "LICENSE_INVALID") {
        // `/api/users` is not on the Limited Mode allow-list, so a lease that
        // lapsed while this page was open kills every call here. Reload so the
        // app falls back to the Activation page rather than showing a dead
        // grid — the same move Monitor makes.
        window.location.reload();
        return;
      }
      message.error(err instanceof ApiRequestError ? err.message : "Could not load users");
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    // The setState lands in a promise callback once the API answers, never
    // synchronously in the effect body.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  const addUser = async (values: NewUser) => {
    setAdding(true);
    try {
      await api.createUser(values);
      message.success(`Added ${values.username}`);
      form.resetFields();
      await refresh();
    } catch (err) {
      message.error(err instanceof ApiRequestError ? err.message : "Could not add the user");
    } finally {
      setAdding(false);
    }
  };

  const changeRole = async (user: User, role: "admin" | "user") => {
    try {
      await api.setUserRole(user.id, role);
      message.success(`${user.username} is now ${role}`);
      await refresh();
    } catch (err) {
      message.error(err instanceof ApiRequestError ? err.message : "Could not change the role");
    }
  };

  const removeUser = async (user: User) => {
    try {
      await api.deleteUser(user.id);
      message.success(`Removed ${user.username}`);
      await refresh();
    } catch (err) {
      message.error(err instanceof ApiRequestError ? err.message : "Could not remove the user");
    }
  };

  const resetPassword = async (values: ResetForm) => {
    if (!resetTarget) return;
    setResetting(true);
    try {
      await api.resetUserPassword(resetTarget.id, values.next);
      message.success(`Password reset. ${resetTarget.username} has been signed out everywhere.`);
      resetFormInstance.resetFields();
      setResetTarget(null);
    } catch (err) {
      message.error(err instanceof ApiRequestError ? err.message : "Could not reset the password");
    } finally {
      setResetting(false);
    }
  };

  const closeReset = () => {
    resetFormInstance.resetFields();
    setResetTarget(null);
  };

  const columns: ColumnsType<User> = [
    {
      title: "Username",
      dataIndex: "username",
      key: "username",
      render: (username: string, user: User) => (
        <Space>
          <Text strong>{username}</Text>
          {user.id === currentUserId ? <Tag>you</Tag> : null}
        </Space>
      ),
    },
    {
      title: "Role",
      dataIndex: "role",
      key: "role",
      render: (role: "admin" | "user", user: User) => (
        <Space>
          <Select
            size="small"
            value={role}
            options={ROLE_OPTIONS}
            style={{ width: 100 }}
            disabled={user.id === currentUserId}
            onChange={(next) => void changeRole(user, next)}
          />
          {role === "admin" ? <Tag color="geekblue">admin</Tag> : null}
        </Space>
      ),
    },
    {
      title: "Created",
      dataIndex: "created_at",
      key: "created_at",
      render: (createdAt: string) => dayjs(createdAt).format("YYYY-MM-DD HH:mm"),
    },
    {
      title: "Actions",
      key: "actions",
      render: (_, user: User) => {
        const isSelf = user.id === currentUserId;
        return (
          <Space>
            <Button
              size="small"
              icon={<KeyOutlined />}
              disabled={isSelf}
              title={isSelf ? "Use Change password in the header" : undefined}
              onClick={() => setResetTarget(user)}
            >
              Reset password
            </Button>
            <Popconfirm
              title={`Remove ${user.username}?`}
              description="Their open sessions end immediately."
              disabled={isSelf}
              onConfirm={() => void removeUser(user)}
            >
              <Button size="small" danger type="text" icon={<DeleteOutlined />} disabled={isSelf} />
            </Popconfirm>
          </Space>
        );
      },
    },
  ];

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <div>
        <Title level={4} style={{ margin: 0 }}>
          User Management
        </Title>
        <Text type="secondary">
          Accounts on this machine. Resetting a password signs that user out everywhere.
        </Text>
      </div>

      <Card size="small" title="Add a user">
        <Form form={form} layout="vertical" onFinish={(values) => void addUser(values)} disabled={adding}>
          <Row gutter={12}>
            <Col xs={24} sm={8} md={6}>
              <Form.Item
                name="username"
                label="Username"
                rules={[
                  { required: true, message: "Choose a username." },
                  { min: 3, message: "Use at least 3 characters." },
                  { max: 64, message: "Use at most 64 characters." },
                ]}
              >
                <Input autoComplete="off" />
              </Form.Item>
            </Col>
            <Col xs={24} sm={8} md={6}>
              <Form.Item
                name="password"
                label="Password"
                rules={[
                  { required: true, message: "Choose a password." },
                  { min: MIN_PASSWORD_LENGTH, message: `Use at least ${MIN_PASSWORD_LENGTH} characters.` },
                ]}
              >
                <Input.Password autoComplete="new-password" />
              </Form.Item>
            </Col>
            <Col xs={24} sm={8} md={4}>
              <Form.Item name="role" label="Role" rules={[{ required: true, message: "Pick a role." }]}>
                <Select placeholder="Select" options={ROLE_OPTIONS} />
              </Form.Item>
            </Col>
          </Row>
          <Button type="primary" htmlType="submit" icon={<UserAddOutlined />} loading={adding}>
            Add user
          </Button>
        </Form>
      </Card>

      <Table<User>
        rowKey="id"
        size="small"
        loading={loading}
        pagination={false}
        dataSource={users}
        columns={columns}
      />

      <Modal
        open={resetTarget !== null}
        title={resetTarget ? `Reset the password for ${resetTarget.username}` : "Reset password"}
        okText="Reset password"
        confirmLoading={resetting}
        onOk={() => void resetFormInstance.submit()}
        onCancel={closeReset}
        destroyOnHidden
      >
        <Form
          form={resetFormInstance}
          layout="vertical"
          onFinish={(values) => void resetPassword(values)}
          disabled={resetting}
        >
          <Form.Item
            name="next"
            label="New password"
            rules={[
              { required: true, message: "Choose a password." },
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
              { required: true, message: "Type the password again." },
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
    </Space>
  );
}
