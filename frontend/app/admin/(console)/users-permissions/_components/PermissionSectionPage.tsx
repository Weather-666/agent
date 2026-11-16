"use client";

import { Button, Card, Input, Space, Table, Tag, Typography, type TableColumnsType } from "antd";
import { useI18n, type Translate } from "@/lib/i18n";

const { Title, Text } = Typography;


type PermissionRow = {
  name: string;
  detail: string;
  status: string;
  meta: string;
};

type PermissionAction = {
  label: string;
  primary?: boolean;
};

type PermissionSectionPageProps = {
  title: string;
  description: string;
  actionLabel: string;
  searchPlaceholder: string;
  columns: {
    primary: string;
    detail: string;
    status: string;
    meta: string;
  };
  rows: PermissionRow[];
  actions: PermissionAction[];
};

function statusTag(status: string, t: Translate) {
  if (status === "active" || status === "enabled") {
    return <Tag color="green">{t("adminUsers.statusEnabled")}</Tag>;
  }
  if (status === "pending") {
    return <Tag color="gold">{t("adminUsers.statusPending")}</Tag>;
  }
  if (status === "system") {
    return <Tag color="geekblue">{t("adminUsers.statusSystem")}</Tag>;
  }
  return <Tag>{status}</Tag>;
}

export function PermissionSectionPage({
  title,
  description,
  actionLabel,
  searchPlaceholder,
  columns,
  rows,
  actions,
}: PermissionSectionPageProps) {
  const { t } = useI18n();

  const tableColumns: TableColumnsType<PermissionRow> = [
    { title: columns.primary, dataIndex: "name", key: "name", render: (name: string) => <span className="font-medium text-[#111827]">{name}</span> },
    { title: columns.detail, dataIndex: "detail", key: "detail" },
    { title: columns.status, key: "status", render: (_, row) => statusTag(row.status, t) },
    { title: columns.meta, dataIndex: "meta", key: "meta" },
    {
      title: t("adminUsers.colActions"),
      key: "actions",
      render: () => (
        <Space wrap>
          {actions.map((action) => (
            <Button key={action.label} size="small" type={action.primary ? "primary" : "default"}>
              {action.label}
            </Button>
          ))}
        </Space>
      ),
    },
  ];

  return (
    <div className="grid gap-[18px]">
      <div>
        <p className="text-xs uppercase tracking-[0.16em] text-[#6b7280]">{t("adminUsers.eyebrow")}</p>
        <Title level={3} className="!mt-1 !mb-0">{t("adminUsers.pageTitle")}</Title>
      </div>

      <Card>
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <Title level={4} className="!mb-1">{title}</Title>
            <Text type="secondary" className="text-sm">{description}</Text>
          </div>
          <Button type="primary">{actionLabel}</Button>
        </div>

        <Input.Search allowClear placeholder={searchPlaceholder} className="mb-3" />

        <Table<PermissionRow>
          rowKey="name"
          columns={tableColumns}
          dataSource={rows}
          scroll={{ x: 920 }}
          pagination={{ defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100] }}
        />
      </Card>
    </div>
  );
}
