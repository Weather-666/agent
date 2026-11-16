"use client";

import { ConfigProvider, theme } from "antd";
import enUS from "antd/locale/en_US";
import zhCN from "antd/locale/zh_CN";
import dayjs from "dayjs";
import "dayjs/locale/zh-cn";
import { useI18n } from "@/lib/i18n";

// Global Ant Design theme + locale bridge. It reads the app's own i18n locale
// (from I18nProvider) and drives antd's ConfigProvider locale so built-in
// component text (pagination, empty state, date pickers…) follows the same
// language switch the rest of the UI uses.
//
// This is context-only: ConfigProvider emits no DOM wrapper or CSS reset, so it
// is safe to mount globally without affecting the (non-antd) user-side pages.
// antd's <App> wrapper — which DOES inject a `.ant-app` font/color reset — is
// mounted separately inside the admin console layout so it stays scoped to
// /admin (see app/admin/(console)/layout.tsx).
//
// The theme tokens keep antd aligned with the existing WinWise brand instead of
// antd's default look: blue accent (#1d4ed8), soft-gray layout background, and
// the sidebar's selected-item colors.
export default function AntdConfigProvider({ children }: { children: React.ReactNode }) {
  const { locale } = useI18n();

  // antd's DatePicker renders calendar month/weekday names via dayjs, whose
  // global locale is independent of ConfigProvider's `locale`. Keep them in
  // sync so the calendar matches the app language (zh-cn / en).
  dayjs.locale(locale === "en-US" ? "en" : "zh-cn");

  return (
    <ConfigProvider
      locale={locale === "en-US" ? enUS : zhCN}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: "#1d4ed8",
          borderRadius: 8,
          colorBgLayout: "#f3f4f8",
          fontFamily: "inherit",
        },
        components: {
          Button: {
            // Admin primary buttons use the near-black brand color (#111827)
            // rather than the blue accent, matching the dark buttons used on
            // the rest of the admin surface. Scoped to Button so links, menu
            // highlight, and progress keep the blue accent above.
            colorPrimary: "#111827",
            colorPrimaryHover: "#1f2937",
            colorPrimaryActive: "#030712",
          },
          Menu: {
            itemSelectedBg: "#eaf0fb",
            itemSelectedColor: "#1d4ed8",
            itemActiveBg: "#eaf0fb",
          },
          Layout: {
            bodyBg: "#f3f4f8",
            headerBg: "#f3f4f8",
            siderBg: "#f7f8fb",
          },
        },
      }}
    >
      {children}
    </ConfigProvider>
  );
}
