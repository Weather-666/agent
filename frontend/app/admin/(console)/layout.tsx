"use client";

import { usePathname, useRouter } from "next/navigation";
import { cloneElement, isValidElement, useEffect, useMemo, useState } from "react";
import { App, Avatar, Dropdown, Layout, Menu, Tag, type MenuProps } from "antd";
import {
  AppstoreOutlined,
  BankOutlined,
  BookOutlined,
  LogoutOutlined,
  SettingOutlined,
  StarOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { getAdminCurrentUser, type LoginUser } from "@/lib/api/auth";
import { ADMIN_AUTH_EXPIRED_EVENT, clearAdminAuthState, getAdminAccessToken } from "@/lib/request";
import { LanguageSwitcher, useI18n, type MessageKey, type Translate } from "@/lib/i18n";

const { Sider, Header, Content } = Layout;

const navItems: Array<{ href: string; labelKey: MessageKey; icon: React.ReactNode }> = [
  { href: "/admin/featured", labelKey: "adminShell.featured", icon: <StarOutlined /> },
  { href: "/admin/knowledge", labelKey: "adminShell.knowledge", icon: <BookOutlined /> },
  { href: "/admin/experts", labelKey: "adminShell.experts", icon: <TeamOutlined /> },
  { href: "/admin/skillsManage", labelKey: "adminShell.skills", icon: <ThunderboltOutlined /> },
  // { href: "/admin/ops", labelKey: "adminShell.ops", icon: <AppstoreOutlined /> },
  { href: "/admin/plans", labelKey: "adminShell.plans", icon: <BankOutlined /> },
];

const accessItems: Array<{ href: string; labelKey: MessageKey; roles?: string[] }> = [
  { href: "/admin/users-permissions/platform-users", labelKey: "adminShell.platformUsers", roles: ["admin", "operator"] },
  { href: "/admin/users-permissions/platform-roles", labelKey: "adminShell.platformRoles", roles: ["admin"] },
  { href: "/admin/users-permissions/tenants", labelKey: "adminShell.tenants" },
  { href: "/admin/users-permissions/tenant-members", labelKey: "adminShell.tenantMembers" },
];

const settingsItems: Array<{ href: string; labelKey: MessageKey }> = [
  { href: "/admin/settings/ai", labelKey: "adminShell.aiSettings" },
  { href: "/admin/settings/notify", labelKey: "adminShell.notifications" },
  { href: "/admin/settings/security", labelKey: "adminShell.security" },
  { href: "/admin/settings/appearance", labelKey: "adminShell.appearance" },
  { href: "/admin/settings/logs", labelKey: "adminShell.logs" },
];

const ACCESS_KEY = "group-access";
const SETTINGS_KEY = "group-settings";

function readCookie(name: string) {
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`));

  return match ? decodeURIComponent(match.split("=")[1] ?? "") : "";
}

function getEmailName(email: string) {
  return email.split("@")[0] || email;
}


function getAdminDisplayName(profile: LoginUser | null, fallbackEmail: string, t: Translate) {
  return profile?.nickname || profile?.username || profile?.email || getEmailName(fallbackEmail) || t("adminShell.adminFallbackName");
}

function getAdminSubtitle(profile: LoginUser | null, fallbackEmail: string, t: Translate) {
  return profile?.email || fallbackEmail || profile?.role || profile?.planName || t("adminShell.adminFallbackName");
}

function getInitial(name: string, t: Translate) {
  return (name.trim().charAt(0) || t("adminShell.adminInitial")).toUpperCase();
}

function getPlatformRolesFromToken(token: string) {
  try {
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

const roleLabelKeys: Record<string, MessageKey> = {
  admin: "adminShell.roleAdmin",
  operator: "adminShell.roleOperator",
  expert: "adminShell.roleExpert",
};

function getRoleLabel(role: string, t: Translate) {
  const key = roleLabelKeys[role];
  return key ? t(key) : role;
}

export default function AdminConsoleLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const { t } = useI18n();
  const pathname = usePathname();
  const router = useRouter();
  const [adminProfile, setAdminProfile] = useState<LoginUser | null>(null);
  const [adminEmail, setAdminEmail] = useState("");
  const [platformRoles, setPlatformRoles] = useState<string[]>([]);
  const [isAuthorizedAdmin, setIsAuthorizedAdmin] = useState(false);

  const adminDisplayName = getAdminDisplayName(adminProfile, adminEmail, t);
  const adminSubtitle = getAdminSubtitle(adminProfile, adminEmail, t);
  const adminInitial = getInitial(adminDisplayName, t);
  const platformRoleLabel = platformRoles.length ? platformRoles.map((role) => getRoleLabel(role, t)).join(" / ") : t("adminShell.roleDefault");
  const visibleAccessItems = useMemo(() => accessItems.filter((item) => {
    if (!item.roles) return true;
    return item.roles.some((role) => platformRoles.includes(role));
  }), [platformRoles]);

  // Build the antd Menu tree: flat top-level links plus two submenu groups.
  const menuItems = useMemo<MenuProps["items"]>(() => [
    ...navItems.map((item) => ({ key: item.href, icon: item.icon, label: t(item.labelKey) })),
    {
      key: ACCESS_KEY,
      icon: <UserOutlined />,
      label: t("adminShell.users"),
      children: visibleAccessItems.map((item) => ({ key: item.href, label: t(item.labelKey) })),
    },
    {
      key: SETTINGS_KEY,
      icon: <SettingOutlined />,
      label: t("adminShell.settings"),
      children: settingsItems.map((item) => ({ key: item.href, label: t(item.labelKey) })),
    },
  ], [t, visibleAccessItems]);

  const isAccessActive = pathname.startsWith("/admin/users-permissions") || pathname === "/admin/usersManage";
  const isSettingsActive = pathname.startsWith("/admin/settings");
  const openKeys = [
    ...(isAccessActive ? [ACCESS_KEY] : []),
    ...(isSettingsActive ? [SETTINGS_KEY] : []),
  ];

  const onMenuClick: MenuProps["onClick"] = ({ key }) => {
    // Submenu parents are handled by their own expand toggle; only leaf routes navigate.
    if (key === ACCESS_KEY || key === SETTINGS_KEY) return;
    router.push(key);
  };

  const onOpenChange: MenuProps["onOpenChange"] = (keys) => {
    // Clicking a group header that isn't in its section jumps to the first child,
    // preserving the old "open section navigates" behavior.
    const opened = keys[keys.length - 1];
    if (opened === ACCESS_KEY && !pathname.startsWith("/admin/users-permissions")) {
      router.push(visibleAccessItems[0]?.href ?? "/admin/featured");
    } else if (opened === SETTINGS_KEY && !pathname.startsWith("/admin/settings")) {
      router.push("/admin/settings/ai");
    }
  };

  useEffect(() => {
    const handleAuthExpired = () => {
      setAdminProfile(null);
      setAdminEmail("");
      setPlatformRoles([]);
      router.replace("/admin/login");
    };

    window.addEventListener(ADMIN_AUTH_EXPIRED_EVENT, handleAuthExpired);
    return () => {
      window.removeEventListener(ADMIN_AUTH_EXPIRED_EVENT, handleAuthExpired);
    };
  }, [router]);

  useEffect(() => {
    queueMicrotask(() => {
      const roles = getPlatformRolesFromToken(getAdminAccessToken());

      if (roles.length) {
        setPlatformRoles(roles);
        setIsAuthorizedAdmin(true);
        return;
      }

      window.localStorage.removeItem("admin_email");
      document.cookie = "ww_demo_admin=; Path=/; Max-Age=0; SameSite=Lax";
      setAdminProfile(null);
      setAdminEmail("");
      setPlatformRoles([]);
      router.replace("/admin/login");
    });
  }, [router]);

  useEffect(() => {
    if (!isAuthorizedAdmin) return;

    let ignore = false;

    queueMicrotask(() => {
      if (ignore) return;
      setAdminEmail(window.localStorage.getItem("admin_email") || readCookie("ww_demo_admin"));
    });

    getAdminCurrentUser()
      .then((profile) => {
        if (ignore) return;
        setAdminProfile(profile);
        if (profile.email) {
          setAdminEmail(profile.email);
          window.localStorage.setItem("admin_email", profile.email);
        }
      })
      .catch(() => {
        if (!ignore) setAdminProfile(null);
      });

    return () => {
      ignore = true;
    };
  }, [isAuthorizedAdmin]);

  useEffect(() => {
    if (!isAuthorizedAdmin || !pathname.startsWith("/admin/users-permissions")) return;
    if (visibleAccessItems.some((item) => item.href === pathname)) return;

    router.replace(visibleAccessItems[0]?.href ?? "/admin/featured");
  }, [isAuthorizedAdmin, pathname, router, visibleAccessItems]);

  const logout = () => {
    clearAdminAuthState();
    router.push("/admin/login");
  };

  const userMenu: MenuProps = {
    items: [
      {
        key: "logout",
        danger: true,
        icon: <LogoutOutlined />,
        label: t("adminShell.logout"),
        onClick: logout,
      },
    ],
  };

  if (!isAuthorizedAdmin) {
    return <div className="h-screen overflow-hidden bg-[#f3f4f8]" />;
  }

  return (
    <App>
    <Layout className="admin-console h-screen">
      <Sider
        width={260}
        theme="light"
        breakpoint="lg"
        collapsedWidth={0}
        className="!bg-[#f7f8fb] border-r border-[#dde2ea]"
      >
        <div className="flex h-full flex-col">
          <div className="shrink-0 px-6 py-6">
            <div className="inline-flex items-center gap-3">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-[#232f3e] text-sm font-bold text-white">W</span>
              <strong className="text-2xl font-bold text-[#111827]">WinWise</strong>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            <Menu
              mode="inline"
              items={menuItems}
              selectedKeys={[pathname]}
              defaultOpenKeys={openKeys}
              onClick={onMenuClick}
              onOpenChange={onOpenChange}
              style={{ background: "transparent", borderInlineEnd: "none" }}
            />
          </div>

          <div className="border-t border-[#e5e7eb] p-4">
            <Dropdown
              menu={userMenu}
              trigger={["click"]}
              placement="topLeft"
              popupRender={(menuNode) => (
                <div className="w-[240px] overflow-hidden rounded-xl border border-[#e5e7eb] bg-white shadow-lg">
                  <div className="flex items-center gap-3 border-b border-[#f0f1f4] p-3">
                    {adminProfile?.avatar ? (
                      <Avatar size={40} src={adminProfile.avatar} alt={adminDisplayName} className="shrink-0" />
                    ) : (
                      <Avatar size={40} className="shrink-0" style={{ backgroundColor: "#e2e8f0", color: "#334155", fontWeight: 700 }}>
                        {adminInitial}
                      </Avatar>
                    )}
                    <div className="min-w-0 flex-1">
                      <strong title={adminDisplayName} className="block truncate text-sm text-[#111827]">{adminDisplayName}</strong>
                      <small title={adminSubtitle} className="block truncate text-xs text-[#6b7280]">{adminSubtitle}</small>
                    </div>
                  </div>
                  <div className="border-b border-[#f0f1f4] px-3 py-2">
                    <Tag color="blue" title={platformRoleLabel} className="!m-0 max-w-full overflow-hidden text-ellipsis whitespace-nowrap">
                      {platformRoleLabel}
                    </Tag>
                  </div>
                  {isValidElement(menuNode)
                    ? cloneElement(menuNode as React.ReactElement<{ style?: React.CSSProperties }>, {
                        style: { boxShadow: "none", borderRadius: 0, background: "transparent" },
                      })
                    : menuNode}
                </div>
              )}
            >
              <button
                type="button"
                title={t("adminShell.openUserMenu")}
                className="flex w-full items-center gap-3 overflow-hidden rounded-xl border border-[#d1d5db] bg-white px-3 py-2 text-left hover:bg-[#f9fafb]"
              >
                {adminProfile?.avatar ? (
                  <Avatar size={36} src={adminProfile.avatar} alt={adminDisplayName} className="shrink-0" />
                ) : (
                  <Avatar size={36} className="shrink-0" style={{ backgroundColor: "#e2e8f0", color: "#334155", fontWeight: 700 }}>
                    {adminInitial}
                  </Avatar>
                )}
                <small title={adminSubtitle} className="min-w-0 flex-1 truncate text-sm text-[#111827]">{adminSubtitle}</small>
              </button>
            </Dropdown>
          </div>
        </div>
      </Sider>

      <Layout>
        <Header className="sticky top-0 z-10 flex items-center justify-end border-b border-[#e5e7eb] !bg-[#f3f4f8] !px-6">
          <LanguageSwitcher />
        </Header>
        <Content className="overflow-y-auto p-6">{children}</Content>
      </Layout>
    </Layout>
    </App>
  );
}
