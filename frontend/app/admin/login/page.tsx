"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { App, Button, Form, Input, Typography } from "antd";
import { EyeInvisibleOutlined, EyeOutlined } from "@ant-design/icons";
import { login } from "@/lib/api/auth";
import { clearAdminAuthState, saveAdminAuthTokens } from "@/lib/request";
import { LanguageSwitcher, useI18n } from "@/lib/i18n";

const { Title, Text } = Typography;

type AccessTokenPayload = {
  platformRoles?: string[];
};

type LoginFormValues = {
  email: string;
  password: string;
};

function decodeAccessToken(token: string): AccessTokenPayload {
  try {
    const payload = token.split(".")[1];
    if (!payload) return {};

    const normalizedPayload = payload.replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(window.atob(normalizedPayload)) as AccessTokenPayload;
  } catch {
    return {};
  }
}

function hasPlatformConsoleAccess(payload: AccessTokenPayload) {
  return Boolean(payload.platformRoles?.length);
}

function getErrorMessage(err: unknown, fallback: string) {
  if (err instanceof Error) return err.message;
  if (err && typeof err === "object" && "message" in err) {
    const message = (err as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }
  return fallback;
}

function AdminLoginForm() {
  const { t } = useI18n();
  const router = useRouter();
  const { message } = App.useApp();
  const [isLoading, setIsLoading] = useState(false);
  const [passwordVisible, setPasswordVisible] = useState(false);

  const handleFinish = async ({ email, password }: LoginFormValues) => {
    if (password.length < 6) {
      message.error(t("auth.adminShortPassword"));
      return;
    }

    setIsLoading(true);
    clearAdminAuthState();

    try {
      const result = await login({ email, password });
      const payload = decodeAccessToken(result.accessToken);

      if (!hasPlatformConsoleAccess(payload)) {
        clearAdminAuthState();
        message.error(t("auth.adminNoAccess"));
        return;
      }

      saveAdminAuthTokens({
        accessToken: result.accessToken,
        refreshToken: result.refreshToken,
      });
      window.localStorage.setItem("admin_email", email);
      document.cookie = `ww_demo_admin=${encodeURIComponent(email)}; Path=/; Max-Age=2592000; SameSite=Lax`;
      message.success(t("auth.adminLoginSuccess"));
      router.replace("/admin/featured");
    } catch (err) {
      clearAdminAuthState();
      message.error(getErrorMessage(err, t("auth.adminLoginFailed")));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="grid min-h-screen place-items-center bg-[rgba(245,246,250,0.84)] px-4">
      <section className="relative w-full max-w-[474px] rounded-2xl bg-[#f5f7fa] px-[56px] pb-7 pt-[34px] text-center text-[#141414] shadow-[0_18px_70px_rgba(24,32,44,0.16)] sm:min-h-[610px]">
        <div className="absolute left-[13px] top-[13px] z-10">
          <LanguageSwitcher />
        </div>

        <div className="mt-[46px] inline-flex items-center gap-2 text-[20px] font-bold tracking-[-0.01em] text-[#232f3e]">
          <span className="grid h-6 w-6 place-items-center rounded-full bg-[#232f3e] text-[13px] font-semibold text-white">
            W
          </span>
          <strong className="font-semibold">WinWise Admin</strong>
        </div>

        <Title level={2} className="mb-3 mt-4 !font-normal [font-family:Georgia,'Times_New_Roman',serif]">
          {t("auth.adminLoginTitle")}
        </Title>
        <Text type="secondary" className="mb-8 block text-[14px]">{t("auth.adminSubtitle")}</Text>

        <Form<LoginFormValues> layout="vertical" onFinish={handleFinish} requiredMark={false} className="text-left">
          <Form.Item
            name="email"
            rules={[{ required: true, message: t("auth.adminNoEmailPassword") }, { type: "email" }]}
          >
            <Input size="large" type="email" autoComplete="email" placeholder={t("auth.adminEmail")} />
          </Form.Item>
          <Form.Item
            name="password"
            rules={[{ required: true, message: t("auth.adminNoEmailPassword") }]}
          >
            <Input
              size="large"
              type={passwordVisible ? "text" : "password"}
              autoComplete="current-password"
              placeholder={t("auth.adminPassword")}
              suffix={
                <span
                  role="button"
                  tabIndex={0}
                  aria-label={passwordVisible ? t("auth.adminHidePassword") : t("auth.adminShowPassword")}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => setPasswordVisible((v) => !v)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setPasswordVisible((v) => !v);
                    }
                  }}
                  className="flex cursor-pointer items-center text-[#8c8c8c] transition-colors hover:text-[#141414]"
                >
                  {passwordVisible ? <EyeOutlined /> : <EyeInvisibleOutlined />}
                </span>
              }
            />
          </Form.Item>

          <Button
            type="primary"
            htmlType="submit"
            size="large"
            block
            loading={isLoading}
            style={{ background: "#232f3e" }}
          >
            {isLoading ? t("auth.adminLoggingIn") : t("auth.adminLoginButton")}
          </Button>
        </Form>

        <Text type="secondary" className="mt-[22px] block text-[12px]">{t("auth.termsNotice")}</Text>
      </section>
    </div>
  );
}

export default function AdminLoginPage() {
  return (
    <App>
      <AdminLoginForm />
    </App>
  );
}
