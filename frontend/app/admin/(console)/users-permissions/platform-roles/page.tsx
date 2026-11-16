"use client";

import { useEffect, useMemo, useState } from "react";
import { App, Card, Input, Space, Table, Tag, Typography, type TableColumnsType } from "antd";
import { getPlatformRoles, type PlatformRole } from "@/lib/api/admin-client";
import { useI18n, type MessageKey, type Translate } from "@/lib/i18n";

const { Title, Text } = Typography;


function getErrorMessage(error: unknown) {
  if (error && typeof error === "object" && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }

  return "";
}

const roleDescriptionKeys: Record<string, MessageKey> = {
  admin: "adminPlatformRoles.descAdmin",
  operator: "adminPlatformRoles.descOperator",
  expert: "adminPlatformRoles.descExpert",
};

function getRoleDescription(role: string, t: Translate) {
  const key = roleDescriptionKeys[role];
  return key ? t(key) : t("adminPlatformRoles.descDefault");
}

export default function PlatformRolesPage() {
  const { t } = useI18n();
  const { message } = App.useApp();
  const [roles, setRoles] = useState<PlatformRole[]>([]);
  const [keyword, setKeyword] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let ignore = false;

    void Promise.resolve()
      .then(() => getPlatformRoles())
      .then((response) => {
        if (ignore) return;
        setRoles(Array.isArray(response.items) ? response.items : []);
      })
      .catch((err) => {
        if (ignore) return;
        message.error(getErrorMessage(err) || t("adminPlatformRoles.loadFailed"));
        setRoles([]);
      })
      .finally(() => {
        if (!ignore) setIsLoading(false);
      });

    return () => {
      ignore = true;
    };
  }, [t, message]);

  const filteredRoles = useMemo(() => {
    const normalizedKeyword = keyword.trim().toLowerCase();
    if (!normalizedKeyword) return roles;

    return roles.filter((item) => {
      const searchable = [
        item.role,
        item.name,
        getRoleDescription(item.role, t),
        ...(item.permissions ?? []),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      return searchable.includes(normalizedKeyword);
    });
  }, [keyword, roles, t]);

  const columns: TableColumnsType<PlatformRole> = [
    { title: t("adminPlatformRoles.colRole"), key: "role", render: (_, item) => <Tag color="geekblue">{item.role}</Tag> },
    { title: t("adminPlatformRoles.colName"), key: "name", render: (_, item) => item.name || item.role },
    { title: t("adminPlatformRoles.colDesc"), key: "desc", render: (_, item) => getRoleDescription(item.role, t) },
    {
      title: t("adminPlatformRoles.colPermissions"),
      key: "permissions",
      render: (_, item) =>
        item.permissions.length ? (
          <Space size={[4, 4]} wrap className="max-w-[520px]">
            {item.permissions.map((permission) => (
              <Tag key={`${item.role}-${permission}`} className="!m-0">{permission}</Tag>
            ))}
          </Space>
        ) : (
          <Text type="secondary">-</Text>
        ),
    },
  ];

  return (
    <div className="grid gap-[18px]">
      <div>
        <p className="text-xs uppercase tracking-[0.16em] text-[#6b7280]">{t("adminUsers.eyebrow")}</p>
        <Title level={3} className="!mt-1 !mb-0">{t("adminUsers.pageTitlePlatformRoles")}</Title>
      </div>

      <Card>
        <div className="mb-4">
          <Title level={4} className="!mb-1">{t("adminPlatformRoles.cardTitle")}</Title>
          <Text type="secondary" className="text-sm">{t("adminPlatformRoles.cardDesc")}</Text>
        </div>

        <Input.Search
          allowClear
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          placeholder={t("adminPlatformRoles.searchPlaceholder")}
          className="mb-3"
          style={{ width: 320 }}
        />

        <Table<PlatformRole>
          rowKey="role"
          columns={columns}
          dataSource={filteredRoles}
          loading={isLoading}
          scroll={{ x: 920 }}
          locale={{ emptyText: keyword ? t("adminPlatformRoles.noMatch") : t("adminPlatformRoles.empty") }}
          pagination={{ defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100] }}
        />
      </Card>
    </div>
  );
}
