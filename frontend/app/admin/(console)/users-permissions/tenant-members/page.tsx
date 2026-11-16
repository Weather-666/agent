"use client";

import { useCallback, useEffect, useState } from "react";
import {
  App,
  Avatar,
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { useI18n, type Translate } from "@/lib/i18n";
import {
  getUser,
  getUsers,
  updateUser,
  updateUserStatus,
  type GetUsersParams,
  type NormalUser,
  type NormalUserDetail,
  type UserStatus,
  type UserTenant,
} from "@/lib/api/admin-client";

const { Title, Text } = Typography;

type AccountStatusFilter = "all" | "active" | "pending_activation" | "disabled";


function formatDate(value?: string | null, withTime = true) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  const day = `${date.getFullYear()}/${String(date.getMonth() + 1).padStart(2, "0")}/${String(date.getDate()).padStart(2, "0")}`;
  if (!withTime) return day;
  return `${day} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function getInitial(user: Pick<NormalUser, "name" | "email">, t: Translate) {
  return (user.name || user.email || t("adminTenantMembers.avatarFallback")).trim().charAt(0).toUpperCase();
}

function joinList(items?: string[]) {
  return items?.length ? items.join(", ") : "-";
}

function statusTag(status: UserStatus, t: Translate) {
  if (status === "active") {
    return <Tag color="green">{t("adminUsers.statusEnabled")}</Tag>;
  }
  if (status === "pending_activation") {
    return <Tag color="gold">{t("adminUsers.statusPending")}</Tag>;
  }
  if (status === "disabled") {
    return <Tag color="red">{t("adminTenantMembers.tagDisabled")}</Tag>;
  }
  return <Tag>{status || t("adminUsers.statusUnknown")}</Tag>;
}

function tenantRoleLabel(role: UserTenant["role"], t: Translate) {
  if (role === "admin") return t("adminTenantMembers.tenantRoleAdmin");
  if (role === "member") return t("adminTenantMembers.tenantRoleMember");
  return role || "-";
}

function tenantTypeLabel(type: UserTenant["type"], t: Translate) {
  if (type === "personal") return t("adminTenantMembers.tenantTypePersonal");
  if (type === "team") return t("adminTenantMembers.tenantTypeTeam");
  return type || "-";
}

function UserDetailPage({ user, onBack }: { user: NormalUserDetail; onBack: () => void }) {
  const { t } = useI18n();

  const tenantColumns: TableColumnsType<UserTenant> = [
    {
      title: t("adminTenantMembers.colTenant"),
      key: "tenant",
      render: (_, tenant) => (
        <div>
          <div className="font-medium text-[#111827]">{tenant.name}</div>
          <div className="mt-1 text-xs text-[#8a8f98]">{tenant.slug}</div>
        </div>
      ),
    },
    { title: t("adminTenantMembers.colType"), key: "type", render: (_, tenant) => tenantTypeLabel(tenant.type, t) },
    { title: t("adminTenantMembers.colTenantRole"), key: "role", render: (_, tenant) => tenantRoleLabel(tenant.role, t) },
    { title: t("adminTenantMembers.colStatus"), key: "status", render: (_, tenant) => tenant.status },
    { title: t("adminTenantMembers.colJoinedAt"), key: "joinedAt", render: (_, tenant) => formatDate(tenant.joinedAt) },
  ];

  return (
    <div className="grid min-w-0 gap-[18px]">
      <Button className="w-fit" icon={<ArrowLeftOutlined />} onClick={onBack}>
        {t("adminTenantMembers.backToList")}
      </Button>

      <Card>
        <div className="flex min-w-0 items-start gap-4">
          <Avatar size={56} style={{ backgroundColor: "#fff4e2", color: "#9a6700", fontWeight: 600 }}>
            {getInitial(user, t)}
          </Avatar>
          <div className="min-w-0">
            <Title level={3} className="!mb-0">{user.name || user.email}</Title>
            <Space size={[8, 8]} wrap className="mt-2">
              {statusTag(user.status, t)}
              <Tag color="geekblue">{t("adminTenantMembers.tenantsLabel")} {user.tenants.length}</Tag>
              <Tag>{t("adminTenantMembers.platformRolesLabel")} {user.platformRoles.length || 0}</Tag>
            </Space>
            <p className="mt-3 text-sm text-[#6b7280]">
              {t("adminTenantMembers.metaLine", { id: user.id, email: user.email, date: formatDate(user.createdAt, false) })}
            </p>
          </div>
        </div>
      </Card>

      <Row gutter={[12, 12]}>
        <Col xs={24} md={8}>
          <Card size="small">
            <Text type="secondary" className="text-sm">{t("adminTenantMembers.accountStatus")}</Text>
            <div className="mt-3">{statusTag(user.status, t)}</div>
            <Text type="secondary" className="mt-3 block text-xs">{t("adminTenantMembers.accountStatusHint")}</Text>
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small">
            <Text type="secondary" className="text-sm">{t("adminTenantMembers.tenantsLabel")}</Text>
            <strong className="mt-3 block text-2xl text-[#111827]">{user.tenants.length}</strong>
            <Text type="secondary" className="mt-2 block text-xs">{t("adminTenantMembers.tenantsHint")}</Text>
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small">
            <Text type="secondary" className="text-sm">{t("adminTenantMembers.platformRolesLabel")}</Text>
            <strong className="mt-3 block break-words text-sm text-[#111827]">{joinList(user.platformRoles)}</strong>
            <Text type="secondary" className="mt-2 block text-xs">{t("adminTenantMembers.platformRolesHint")}</Text>
          </Card>
        </Col>
      </Row>

      <Row gutter={[18, 18]}>
        <Col xs={24} xl={15}>
          <div className="grid gap-[18px]">
            <Card title={t("adminTenantMembers.cardAccountInfo")}>
              <Descriptions column={{ xs: 1, sm: 2 }} size="small">
                <Descriptions.Item label={t("adminTenantMembers.fieldUserId")}>{user.id}</Descriptions.Item>
                <Descriptions.Item label={t("adminTenantMembers.fieldName")}>{user.name || "-"}</Descriptions.Item>
                <Descriptions.Item label={t("adminTenantMembers.fieldEmail")}>{user.email}</Descriptions.Item>
                <Descriptions.Item label={t("adminTenantMembers.accountStatus")}>{statusTag(user.status, t)}</Descriptions.Item>
                <Descriptions.Item label={t("adminTenantMembers.fieldRegisteredAt")}>{formatDate(user.createdAt)}</Descriptions.Item>
                <Descriptions.Item label={t("adminTenantMembers.fieldUpdatedAt")}>{formatDate(user.updatedAt)}</Descriptions.Item>
              </Descriptions>
            </Card>

            <Card title={t("adminTenantMembers.tenantsLabel")}>
              <Table<UserTenant>
                rowKey="id"
                columns={tenantColumns}
                dataSource={user.tenants}
                size="small"
                scroll={{ x: 720 }}
                locale={{ emptyText: t("adminTenantMembers.noTenants") }}
                pagination={false}
              />
            </Card>
          </div>
        </Col>

        <Col xs={24} xl={9}>
          <div className="grid content-start gap-[18px]">
            <Card title={t("adminTenantMembers.cardPermissionInfo")}>
              <div className="grid gap-4">
                <div>
                  <Text type="secondary" className="text-sm">{t("adminTenantMembers.platformRolesLabel")}</Text>
                  <strong className="mt-1 block break-words text-sm text-[#111827]">{joinList(user.platformRoles)}</strong>
                </div>
                <div>
                  <Text type="secondary" className="text-sm">{t("adminTenantMembers.fieldPlatformPermissions")}</Text>
                  <strong className="mt-1 block break-words text-sm text-[#111827]">{joinList(user.platformPermissions)}</strong>
                </div>
              </div>
            </Card>

            <Card title={t("adminTenantMembers.cardManagementActions")}>
              <div className="grid gap-2">
                <Button block>{t("adminTenantMembers.resetPassword")}</Button>
                <Button block>{t("adminTenantMembers.adjustRoles")}</Button>
                <Button block danger>
                  {user.status === "disabled" ? t("adminTenantMembers.enableAccount") : t("adminTenantMembers.disableAccount")}
                </Button>
              </div>
            </Card>
          </div>
        </Col>
      </Row>
    </div>
  );
}

type EditFormValues = { name: string };

export default function TenantMembersPage() {
  const { t } = useI18n();
  const { message } = App.useApp();
  const [editForm] = Form.useForm<EditFormValues>();
  const [users, setUsers] = useState<NormalUser[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [keyword, setKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState<AccountStatusFilter>("all");
  const [isLoading, setIsLoading] = useState(true);
  const [detailUser, setDetailUser] = useState<NormalUserDetail | null>(null);
  const [editingUser, setEditingUser] = useState<NormalUser | null>(null);
  const [statusUser, setStatusUser] = useState<NormalUser | null>(null);

  const loadUsers = useCallback(async () => {
    setIsLoading(true);

    const params: GetUsersParams = {
      page,
      pageSize,
    };
    if (keyword.trim()) params.search = keyword.trim();

    try {
      const response = await getUsers(params);
      const items = Array.isArray(response.items) ? response.items : [];
      const filteredItems = statusFilter === "all" ? items : items.filter((user) => user.status === statusFilter);
      setUsers(filteredItems);
      setTotal(statusFilter === "all" ? response.total ?? 0 : filteredItems.length);
    } catch (err) {
      setUsers([]);
      setTotal(0);
      message.error(err instanceof Error ? err.message : t("adminTenantMembers.loadError"));
    } finally {
      setIsLoading(false);
    }
  }, [keyword, page, pageSize, statusFilter, t, message]);

  useEffect(() => {
    void Promise.resolve().then(loadUsers);
  }, [loadUsers]);

  async function openDetail(userId: string) {
    try {
      setDetailUser(await getUser(userId));
    } catch (err) {
      message.error(err instanceof Error ? err.message : t("adminTenantMembers.detailLoadError"));
    }
  }

  function openEdit(user: NormalUser) {
    setEditingUser(user);
    editForm.setFieldsValue({ name: user.name ?? "" });
  }

  async function handleEditSubmit({ name }: EditFormValues) {
    if (!editingUser) return;

    try {
      const updated = await updateUser(editingUser.id, { name: name.trim() || undefined });
      setEditingUser(null);
      message.success(t("adminTenantMembers.updateSuccess"));
      setUsers((prev) => prev.map((user) => (user.id === updated.id ? { ...user, ...updated } : user)));
    } catch (err) {
      message.error(err instanceof Error ? err.message : t("adminTenantMembers.saveError"));
    }
  }

  async function handleStatusChange() {
    if (!statusUser) return;

    const nextStatus = statusUser.status === "disabled" ? "active" : "disabled";
    try {
      const updated = await updateUserStatus(statusUser.id, { status: nextStatus });
      setStatusUser(null);
      message.success(nextStatus === "disabled" ? t("adminTenantMembers.userDisabled") : t("adminTenantMembers.userEnabled"));
      setUsers((prev) => prev.map((user) => (user.id === updated.id ? { ...user, ...updated } : user)));
    } catch (err) {
      message.error(err instanceof Error ? err.message : t("adminTenantMembers.statusUpdateError"));
    }
  }

  if (detailUser) {
    return <UserDetailPage user={detailUser} onBack={() => setDetailUser(null)} />;
  }

  const columns: TableColumnsType<NormalUser> = [
    {
      title: t("adminTenantMembers.colUser"),
      key: "user",
      render: (_, user) => (
        <div className="flex min-w-[180px] items-center gap-3">
          <Avatar size={36} style={{ backgroundColor: "#fff4e2", color: "#9a6700", fontWeight: 600 }}>
            {getInitial(user, t)}
          </Avatar>
          <div className="min-w-0">
            <div className="font-medium text-[#111827]">{user.name || user.email || user.id}</div>
            <div className="mt-1 truncate text-xs text-[#8a8f98]">{user.email || user.id}</div>
          </div>
        </div>
      ),
    },
    { title: t("adminTenantMembers.accountStatus"), key: "status", render: (_, user) => statusTag(user.status, t) },
    { title: t("adminTenantMembers.platformRolesLabel"), key: "roles", render: (_, user) => joinList(user.platformRoles) },
    { title: t("adminTenantMembers.colTenantCount"), key: "tenantCount", render: (_, user) => user.tenantCount },
    { title: t("adminTenantMembers.fieldRegisteredAt"), key: "createdAt", render: (_, user) => formatDate(user.createdAt) },
    {
      title: t("adminUsers.colActions"),
      key: "actions",
      fixed: "right",
      width: 220,
      render: (_, user) => (
        <Space wrap>
          <Button size="small" onClick={() => void openDetail(user.id)}>{t("adminTenantMembers.actionView")}</Button>
          <Button size="small" onClick={() => openEdit(user)}>{t("adminTenantMembers.actionEdit")}</Button>
          <Button size="small" danger onClick={() => setStatusUser(user)}>
            {user.status === "disabled" ? t("adminTenantMembers.actionEnable") : t("adminTenantMembers.actionDisable")}
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div className="grid min-w-0 gap-[18px]">
      <div>
        <p className="text-xs uppercase tracking-[0.16em] text-[#6b7280]">{t("adminUsers.eyebrow")}</p>
        <Title level={3} className="!mt-1 !mb-0">{t("adminUsers.pageTitleTenantMembers")}</Title>
      </div>

      <Card>
        <div className="mb-4">
          <Title level={4} className="!mb-1">{t("adminTenantMembers.sectionTitle")}</Title>
          <Text type="secondary" className="text-sm">{t("adminTenantMembers.sectionDesc")}</Text>
        </div>

        <Space size="middle" wrap className="mb-3 w-full">
          <Input.Search
            allowClear
            value={keyword}
            onChange={(event) => {
              setPage(1);
              setKeyword(event.target.value);
            }}
            placeholder={t("adminTenantMembers.searchPlaceholder")}
            style={{ width: 280 }}
          />
          <Select
            value={statusFilter}
            onChange={(value) => {
              setPage(1);
              setStatusFilter(value);
            }}
            style={{ width: 180 }}
            options={[
              { value: "all", label: t("adminTenantMembers.filterAllStatuses") },
              { value: "active", label: t("adminUsers.statusEnabled") },
              { value: "pending_activation", label: t("adminUsers.statusPending") },
              { value: "disabled", label: t("adminTenantMembers.filterStatusDisabled") },
            ]}
          />
        </Space>

        <Table<NormalUser>
          rowKey="id"
          columns={columns}
          dataSource={users}
          loading={isLoading}
          scroll={{ x: 980 }}
          locale={{ emptyText: keyword || statusFilter !== "all" ? t("adminTenantMembers.noMatchingMembers") : t("adminTenantMembers.noMembers") }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50, 100],
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
            },
          }}
        />
      </Card>

      <Modal
        open={Boolean(editingUser)}
        title={t("adminTenantMembers.editMemberTitle")}
        width={520}
        onCancel={() => setEditingUser(null)}
        okText={t("adminTenantMembers.save")}
        cancelText={t("common.dialogCancel")}
        onOk={() => editForm.submit()}
      >
        {editingUser ? <Text type="secondary" className="mb-3 block text-sm">{editingUser.email}</Text> : null}
        <Form<EditFormValues> form={editForm} layout="vertical" onFinish={handleEditSubmit}>
          <Form.Item name="name" label={t("adminTenantMembers.fieldUserName")}>
            <Input placeholder={t("adminTenantMembers.userNamePlaceholder")} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={Boolean(statusUser)}
        title={statusUser?.status === "disabled" ? t("adminTenantMembers.enableUserTitle") : t("adminTenantMembers.disableUserTitle")}
        width={440}
        onCancel={() => setStatusUser(null)}
        okText={t("adminTenantMembers.confirm")}
        cancelText={t("adminTenantMembers.cancel")}
        onOk={() => void handleStatusChange()}
      >
        {statusUser ? (
          <Text className="text-sm text-[#6b7280]">
            {statusUser.status === "disabled"
              ? t("adminTenantMembers.confirmEnable", { email: statusUser.email })
              : t("adminTenantMembers.confirmDisable", { email: statusUser.email })}
          </Text>
        ) : null}
      </Modal>
    </div>
  );
}
