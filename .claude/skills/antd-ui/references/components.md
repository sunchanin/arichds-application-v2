# Components — project-correct snippets (copy these), context7 for full props

These snippets already encode the project conventions (vertical forms, server-side
pagination, `App.useApp()`, `options`/`items` props) — **copy them as the starting
point.** They work offline; they don't depend on a context7 round-trip.

When you need the **exhaustive prop list** or a prop these snippets don't show,
query context7 to confirm the current API — but the *composition* below is the
project rule, not whatever the generic upstream demo shows.

- context7 library ID: **`/ant-design/ant-design`** → `query-docs`
- Every snippet assumes a `"use client"` file.

---

## Button

```tsx
import { Button } from "antd";

<Button type="primary" onClick={onSave}>Save</Button>
<Button type="primary" danger loading={saving}>Delete</Button>
```

Full props (`type | danger | loading | icon | htmlType | size`) → context7:
*"antd Button props htmlType size icon"*. Use `htmlType="submit"` inside a Form.

---

## Input / InputNumber

```tsx
import { Input, InputNumber } from "antd";

<Input placeholder="Name" allowClear />
<Input.Password placeholder="Password" />
<Input.TextArea rows={4} maxLength={500} showCount />
<InputNumber min={0} max={100} style={{ width: "100%" }} />
```

Inside a `Form.Item`, don't wire `value`/`onChange` — the form owns it.
`Input.Search/Password/TextArea` are fine to use directly.

---

## Select

**Project rule: feed via `options` prop, never `<Select.Option>` children** (RSC
dot-notation caveat — `setup-nextjs.md`).

```tsx
import { Select } from "antd";

<Select
  placeholder="Pick a role"
  allowClear
  showSearch
  optionFilterProp="label"
  style={{ width: "100%" }}
  options={[
    { value: "admin", label: "Admin" },
    { value: "editor", label: "Editor" },
  ]}
/>
```

`mode="multiple"`/`"tags"` for multi. Server-driven search → context7:
*"antd Select showSearch server-driven debounced options loading"*.

---

## Form

**Project rule: `layout="vertical"` always; feedback via `App.useApp()`.**

```tsx
import { Form, Input, Select, Button, App } from "antd";

export function UserForm({ onSubmit }: { onSubmit: (v: Values) => Promise<void> }) {
  const [form] = Form.useForm();
  const { message } = App.useApp();

  const handleFinish = async (values: Values) => {
    try {
      await onSubmit(values);
      message.success("Saved");
    } catch {
      message.error("Failed to save");
    }
  };

  return (
    <Form form={form} layout="vertical" onFinish={handleFinish} requiredMark>
      <Form.Item name="name" label="Name" rules={[{ required: true }]}>
        <Input />
      </Form.Item>
      <Form.Item name="email" label="Email" rules={[{ required: true, type: "email" }]}>
        <Input />
      </Form.Item>
      <Form.Item name="role" label="Role" rules={[{ required: true }]}>
        <Select options={[{ value: "admin", label: "Admin" }]} />
      </Form.Item>
      <Form.Item>
        <Button type="primary" htmlType="submit">Submit</Button>
      </Form.Item>
    </Form>
  );
}
```

Instance methods (`setFieldsValue`, `resetFields`, `validateFields`,
`Form.useWatch`) → context7: *"antd Form.useForm instance methods, Form.useWatch"*.

---

## Table

**Project rule: server-side pagination always** — keep page/sort/filter in state,
refetch on `onChange`, pass `total`. Never hand antd the full dataset (the generic
antd demo paginates client-side — do NOT follow it). Type columns with
`TableColumnsType<Row>` (the public type from `antd` — prefer it over the internal
`ColumnsType` deep-import from `antd/es/table`).

```tsx
import { Table } from "antd";
import type { TableColumnsType, TablePaginationConfig } from "antd";
import { useState } from "react";

const columns: TableColumnsType<Row> = [
  { title: "Name", dataIndex: "name", key: "name" },
  { title: "Email", dataIndex: "email", key: "email" },
  {
    title: "Action",
    key: "action",
    render: (_, row) => <a onClick={() => edit(row.id)}>Edit</a>,
  },
];

export function UsersTable({ initialRows, total }: Props) {
  const [rows, setRows] = useState(initialRows);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [count, setCount] = useState(total);

  const handleChange = async (p: TablePaginationConfig) => {
    setLoading(true);
    const next = await fetchUsers({ page: p.current!, pageSize: p.pageSize! });
    setRows(next.rows);
    setCount(next.total);
    setPage(p.current!);
    setPageSize(p.pageSize!);
    setLoading(false);
  };

  return (
    <Table<Row>
      rowKey="id"
      columns={columns}
      dataSource={rows}              // only the current page's rows
      loading={loading}
      onChange={handleChange}
      pagination={{
        current: page,
        pageSize,
        total: count,               // REQUIRED for server-side paging
        showSizeChanger: true,
      }}
    />
  );
}
```

---

## Modal

Custom content → component form with `open` state. Quick confirm →
`App.useApp()` `modal.confirm` (inherits theme).

```tsx
// custom content
import { Modal } from "antd";
const [open, setOpen] = useState(false);
<Modal title="Edit user" open={open} onOk={save} onCancel={() => setOpen(false)} confirmLoading={saving}>
  <UserForm onSubmit={save} />
</Modal>

// quick confirm (theme-correct)
const { modal } = App.useApp();
modal.confirm({ title: "Delete user?", content: "Cannot be undone.", okType: "danger", onOk: () => deleteUser(id) });
```

---

## message / notification

**Project rule: always via `App.useApp()`**, never the static `message.success()`
import (renders outside `ConfigProvider`, loses the theme — rationale in
`patterns.md`).

```tsx
import { App } from "antd";

const { message, notification } = App.useApp();
message.success("Saved");
notification.info({ message: "Export ready", description: "Your CSV finished." });
```

`<App>` is mounted in `ThemeProvider`, so `App.useApp()` works anywhere.

---

## Layout

```tsx
import { Layout, Menu } from "antd";
const { Header, Sider, Content } = Layout;

<Layout style={{ minHeight: "100vh" }}>
  <Sider collapsible>
    <Menu theme="dark" mode="inline" items={menuItems} />
  </Sider>
  <Layout>
    <Header />
    <Content style={{ margin: 16 }}>{children}</Content>
  </Layout>
</Layout>
```

`Header/Sider/Content/Footer` are fine. **Feed `Menu` via `items` prop**, not
`<Menu.Item>` children. Custom chrome colors/spacing from theme tokens
(`theming.md`).
