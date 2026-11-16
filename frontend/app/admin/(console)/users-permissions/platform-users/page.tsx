"use client";

import { useEffect, useMemo, useState } from "react";
import {
  App,
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  Modal,
  Space,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "antd";
import {
  createPlatformUser,
  getPlatformUsers,
  grantPlatformRole,
  revokePlatformRole,
  type CreatePlatformUserResponse,
  type PlatformUser,
} from "@/lib/api/admin-client";
import { getAccessToken } from "@/lib/request";
import { useI18n, type Translate } from "@/lib/i18n";

const { Title, Text } = Typography;


const allPlatformRoleOptions = ["expert", "operator", "admin"];

function formatDate(value?: string) {
  if (!value) return "-";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return `${date.getFullYear()}/${String(date.getMonth() + 1).padStart(2, "0")}/${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function statusTag(status = "", t: Translate) {
  if (status === "active" || status === "enabled") {
    return <Tag color="green">{t("adminUsers.statusEnabled")}</Tag>;
  }
  if (status === "pending_activation" || status === "pending") {
    return <Tag color="gold">{t("adminUsers.statusPending")}</Tag>;
  }
  if (status === "disabled") {
    return <Tag color="red">{t("adminUsers.statusDisabled")}</Tag>;
  }
  return <Tag>{status || t("adminUsers.statusUnknown")}</Tag>;
}

function getErrorMessage(error: unknown, t: Translate) {
  if (error && typeof error === "object" && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }

  return t("adminPlatformUsers.actionFailed");
}

function joinList(items?: string[]) {
  return items?.length ? items.join(", ") : "-";
}

function buildActivationLink(token: string) {
  if (typeof window === "undefined") return `/platform/activate?token=${encodeURIComponent(token)}`;
  return `${window.location.origin}/platform/activate?token=${encodeURIComponent(token)}`;
}

function getPlatformRolesFromToken() {
  try {
    const token = getAccessToken();
    const payload = token.split(".")[1];
    if (!payload) return [];

    const normalizedPayload = payload.replace(/-/g, "+").replace(/_/g, "/");
    const claims = JSON.parse(window.atob(normalizedPayload)) as {
      platformRoles?: string[];
    };

    return claims.platformRoles ?? [];
  } catch {
    return [];
  }
}

function getManageableRoleOptions(currentRoles: string[]) {
  if (currentRoles.includes("admin")) return allPlatformRoleOptions;
  if (currentRoles.includes("operator")) return ["expert", "operator"];
  return [];
}

type CreateFormValues = { email: string; roles: string[] };

export default function PlatformUsersPage() {
  const { t } = useI18n();
  const { message } = App.useApp();
  const [createForm] = Form.useForm<CreateFormValues>();
  const [users, setUsers] = useState<PlatformUser[]>([]);
  const [currentRoles, setCurrentRoles] = useState<string[]>([]);
  const [keyword, setKeyword] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [createdInvite, setCreatedInvite] = useState<CreatePlatformUserResponse | null>(null);
  const [roleTarget, setRoleTarget] = useState<PlatformUser | null>(null);
  const [roleAction, setRoleAction] = useState("");

  const manageableRoleOptions = useMemo(() => getManageableRoleOptions(currentRoles), [currentRoles]);
  const canCreatePlatformUser = manageableRoleOptions.length > 0;
  const activationLink = createdInvite ? buildActivationLink(createdInvite.activationToken) : "";

  async function loadUsers() {
    setIsLoading(true);

    try {
      const response = await getPlatformUsers();
      setUsers(Array.isArray(response.items) ? response.items : []);
    } catch (err) {
      message.error(getErrorMessage(err, t));
      setUsers([]);
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void Promise.resolve().then(() => {
      const roles = getPlatformRolesFromToken();
      setCurrentRoles(roles);
      return loadUsers();
    });
    // Runs once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filteredUsers = useMemo(() => {
    const normalizedKeyword = keyword.trim().toLowerCase();
    if (!normalizedKeyword) return users;

    return users.filter((user) => {
      const searchable = [
        user.id,
        user.name,
        user.email,
        user.status,
        user.activeTenantId,
        ...(user.platformRoles ?? []),
        ...(user.platformPermissions ?? []),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      return searchable.includes(normalizedKeyword);
    });
  }, [keyword, users]);

  function openCreateModal() {
    setCreatedInvite(null);
    createForm.setFieldsValue({
      email: "",
      roles: manageableRoleOptions.includes("expert") ? ["expert"] : [],
    });
    setIsCreateOpen(true);
  }

  async function handleCreatePlatformUser(values: CreateFormValues) {
    if (!canCreatePlatformUser) {
      message.error(t("adminPlatformUsers.cannotCreate"));
      return;
    }
    if (!values.roles?.length) {
      message.error(t("adminPlatformUsers.selectAtLeastOne"));
      return;
    }
    const unsafeRoles = values.roles.filter((role) => !manageableRoleOptions.includes(role));
    if (unsafeRoles.length) {
      message.error(t("adminPlatformUsers.cannotAssignSelected"));
      return;
    }

    setIsCreating(true);
    setCreatedInvite(null);

    try {
      const email = values.email.trim();
      const created = await createPlatformUser({
        email,
        name: email.split("@")[0] || email,
        roles: values.roles,
      });

      setCreatedInvite(created);
      message.success(t("adminPlatformUsers.createdInvite"));
      createForm.setFieldsValue({
        email: "",
        roles: manageableRoleOptions.includes("expert") ? ["expert"] : [],
      });
      await loadUsers();
    } catch (err) {
      message.error(getErrorMessage(err, t));
    } finally {
      setIsCreating(false);
    }
  }

  async function handleRoleChange(role: string, action: "grant" | "revoke") {
    if (!roleTarget) return;

    if (!manageableRoleOptions.includes(role)) {
      message.error(t("adminPlatformUsers.cannotOperateRole"));
      return;
    }

    setRoleAction(`${action}:${role}`);

    try {
      if (action === "grant") {
        await grantPlatformRole(roleTarget.id, role);
        setRoleTarget({
          ...roleTarget,
          platformRoles: Array.from(new Set([...(roleTarget.platformRoles ?? []), role])),
        });
        message.success(t("adminPlatformUsers.granted", { email: roleTarget.email, role }));
      } else {
        await revokePlatformRole(roleTarget.id, role);
        setRoleTarget({
          ...roleTarget,
          platformRoles: (roleTarget.platformRoles ?? []).filter((item) => item !== role),
        });
        message.success(t("adminPlatformUsers.revoked", { email: roleTarget.email, role }));
      }

      await loadUsers();
    } catch (err) {
      message.error(getErrorMessage(err, t));
    } finally {
      setRoleAction("");
    }
  }

  async function copyActivationLink() {
    if (!activationLink) return;

    try {
      await navigator.clipboard.writeText(activationLink);
      message.success(t("adminPlatformUsers.linkCopied"));
    } catch {
      message.error(t("adminPlatformUsers.copyFailed"));
    }
  }

  const columns: TableColumnsType<PlatformUser> = [
    {
      title: t("adminPlatformUsers.colPerson"),
      key: "person",
      render: (_, user) => (
        <div>
          <div className="font-medium text-[#111827]">{user.name || user.email || user.id}</div>
          <div className="mt-1 text-xs text-[#8a8f98]">{user.email || user.id}</div>
        </div>
      ),
    },
    { title: t("adminPlatformUsers.colStatus"), key: "status", render: (_, user) => statusTag(user.status, t) },
    { title: t("adminPlatformUsers.colRoles"), key: "roles", render: (_, user) => joinList(user.platformRoles) },
    {
      title: t("adminPlatformUsers.colPermissions"),
      key: "permissions",
      render: (_, user) => (
        <div className="max-w-[260px] truncate" title={joinList(user.platformPermissions)}>
          {joinList(user.platformPermissions)}
        </div>
      ),
    },
    { title: t("adminPlatformUsers.colActiveTenant"), key: "activeTenant", render: (_, user) => user.activeTenantId || "-" },
    { title: t("adminPlatformUsers.colCreatedAt"), key: "createdAt", render: (_, user) => formatDate(user.createdAt) },
    { title: t("adminPlatformUsers.colUpdatedAt"), key: "updatedAt", render: (_, user) => formatDate(user.updatedAt) },
    {
      title: t("adminUsers.colActions"),
      key: "actions",
      render: (_, user) => (
        <Button type="primary" size="small" onClick={() => setRoleTarget(user)}>
          {t("adminPlatformUsers.assignRole")}
        </Button>
      ),
    },
  ];

  return (
    <div className="grid gap-[18px]">
      <div>
        <p className="text-xs uppercase tracking-[0.16em] text-[#6b7280]">{t("adminUsers.eyebrow")}</p>
        <Title level={3} className="!mt-1 !mb-0">{t("adminUsers.pageTitlePlatformUsers")}</Title>
      </div>

      <Card>
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <Title level={4} className="!mb-1">{t("adminPlatformUsers.cardTitle")}</Title>
            <Text type="secondary" className="text-sm">{t("adminPlatformUsers.cardDesc")}</Text>
          </div>
          <Button type="primary" disabled={!canCreatePlatformUser} onClick={openCreateModal}>
            {t("adminPlatformUsers.addUser")}
          </Button>
        </div>

        <Input.Search
          allowClear
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          placeholder={t("adminPlatformUsers.searchPlaceholder")}
          className="mb-3"
          style={{ width: 320 }}
        />

        <Table<PlatformUser>
          rowKey="id"
          columns={columns}
          dataSource={filteredUsers}
          loading={isLoading}
          scroll={{ x: 1100 }}
          locale={{ emptyText: keyword ? t("adminPlatformUsers.noMatch") : t("adminPlatformUsers.empty") }}
          pagination={{ defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100] }}
        />
      </Card>

      <Modal
        open={isCreateOpen}
        title={t("adminPlatformUsers.createModalTitle")}
        width={620}
        onCancel={() => setIsCreateOpen(false)}
        okText={isCreating ? t("adminPlatformUsers.creating") : t("adminPlatformUsers.createAndInvite")}
        okButtonProps={{ disabled: !canCreatePlatformUser, loading: isCreating }}
        cancelText={t("common.dialogCancel")}
        onOk={() => createForm.submit()}
      >
        <Text type="secondary" className="mb-3 block text-sm">
          {currentRoles.includes("admin")
            ? t("adminPlatformUsers.createHintAdmin")
            : t("adminPlatformUsers.createHintOperator")}
        </Text>

        <Form<CreateFormValues> form={createForm} layout="vertical" onFinish={handleCreatePlatformUser}>
          <Form.Item
            name="email"
            label={t("adminPlatformUsers.email")}
            rules={[{ required: true, type: "email" }]}
          >
            <Input placeholder="expert@example.com" />
          </Form.Item>
          <Form.Item name="roles" label={t("adminPlatformUsers.roles")}>
            <Checkbox.Group options={manageableRoleOptions.map((role) => ({ label: role, value: role }))} />
          </Form.Item>
        </Form>

        {createdInvite ? (
          <div className="mt-2 rounded-[8px] border border-[#d6e6ff] bg-[#f5f9ff] p-3">
            <p className="text-sm font-medium text-[#111827]">{t("adminPlatformUsers.activationLink")}</p>
            <p className="mt-1 text-xs text-[#6b7280]">
              {t("adminPlatformUsers.expiresAt", { time: formatDate(createdInvite.activationExpiresAt) })}
            </p>
            <Space.Compact className="mt-2 w-full">
              <Input readOnly value={activationLink} />
              <Button type="primary" onClick={copyActivationLink}>{t("adminPlatformUsers.copy")}</Button>
            </Space.Compact>
          </div>
        ) : null}
      </Modal>

      <Modal
        open={Boolean(roleTarget)}
        title={t("adminPlatformUsers.roleModalTitle")}
        width={560}
        footer={null}
        onCancel={() => setRoleTarget(null)}
      >
        {roleTarget ? (
          <>
            <Text type="secondary" className="mb-3 block text-sm">
              {t("adminPlatformUsers.roleModalSubtitle", {
                name: roleTarget.name || roleTarget.email,
                roles: joinList(roleTarget.platformRoles),
              })}
            </Text>
            <div className="grid gap-2">
              {manageableRoleOptions.map((role) => {
                const hasRole = roleTarget.platformRoles?.includes(role) ?? false;
                const action = hasRole ? "revoke" : "grant";
                const isWorking = roleAction === `${action}:${role}`;

                return (
                  <div key={role} className="flex items-center justify-between gap-3 rounded-[8px] border border-[#e6e6e3] px-3 py-3">
                    <div>
                      <p className="text-sm font-medium text-[#111827]">{role}</p>
                      <p className="mt-1 text-xs text-[#8a8f98]">
                        {hasRole ? t("adminPlatformUsers.alreadyHasRole") : t("adminPlatformUsers.noRoleYet")}
                      </p>
                    </div>
                    <Button
                      size="small"
                      danger={hasRole}
                      type={hasRole ? "default" : "primary"}
                      loading={isWorking}
                      disabled={Boolean(roleAction)}
                      onClick={() => void handleRoleChange(role, action)}
                    >
                      {hasRole ? t("adminPlatformUsers.revoke") : t("adminPlatformUsers.grant")}
                    </Button>
                  </div>
                );
              })}
            </div>
          </>
        ) : null}
      </Modal>
    </div>
  );
}
