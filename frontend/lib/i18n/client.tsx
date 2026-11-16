"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useSyncExternalStore } from "react";
import { Select } from "antd";
import { GlobalOutlined } from "@ant-design/icons";
import { defaultLocale, isLocale, localeLabels, locales, translate, translateList, type Locale, type MessageKey, type MessageListKey } from "./messages";

export type Translate = (key: MessageKey, values?: Record<string, string | number>) => string;
type TranslateList = (key: MessageListKey) => string[];

type I18nContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: Translate;
  tList: TranslateList;
};

const storageKey = "winwise-locale";

const I18nContext = createContext<I18nContextValue | null>(null);

function hasAuthState() {
  if (typeof window === "undefined") return false;
  return Boolean(
    window.localStorage.getItem("access_token") ||
      window.localStorage.getItem("user_email") ||
      window.localStorage.getItem("admin_email"),
  );
}

function getSystemLocale() {
  if (typeof window === "undefined") return defaultLocale;

  const languages = window.navigator.languages?.length ? window.navigator.languages : [window.navigator.language];
  const matchedLocale = languages.find((language) => language.toLowerCase().startsWith("zh"));

  return matchedLocale ? "zh-CN" : "en-US";
}

function readInitialLocale() {
  if (typeof window === "undefined") return defaultLocale;

  if (!hasAuthState()) return getSystemLocale();

  const storedLocale = window.localStorage.getItem(storageKey);
  return isLocale(storedLocale) ? storedLocale : getSystemLocale();
}

type LocaleListener = () => void;

const localeListeners = new Set<LocaleListener>();
let clientLocale: Locale | null = null;

// 客户端快照：首次读取时根据浏览器/存储解析真实 locale 并缓存，保持引用稳定。
function getLocaleSnapshot(): Locale {
  if (clientLocale === null) {
    clientLocale = readInitialLocale();
  }
  return clientLocale;
}

// 服务端快照：始终 defaultLocale，保证 SSR 与客户端首帧一致。
function getServerLocaleSnapshot(): Locale {
  return defaultLocale;
}

function subscribeLocale(listener: LocaleListener) {
  localeListeners.add(listener);
  return () => {
    localeListeners.delete(listener);
  };
}

function updateLocale(nextLocale: Locale) {
  clientLocale = nextLocale;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(storageKey, nextLocale);
    document.documentElement.lang = nextLocale;
  }
  localeListeners.forEach((listener) => listener());
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  // 通过 useSyncExternalStore 让首帧（SSR 与客户端 hydration）统一使用
  // defaultLocale，hydration 完成后再切换到真实 locale，从而避免 hydration
  // mismatch，且不会在 effect 内同步调用 setState。
  const locale = useSyncExternalStore(
    subscribeLocale,
    getLocaleSnapshot,
    getServerLocaleSnapshot,
  );

  const setLocale = useCallback((nextLocale: Locale) => {
    updateLocale(nextLocale);
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const t = useCallback<Translate>((key, values) => translate(locale, key, values), [locale]);
  const tList = useCallback<TranslateList>((key) => translateList(locale, key), [locale]);

  const value = useMemo(() => ({ locale, setLocale, t, tList }), [locale, setLocale, t, tList]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const context = useContext(I18nContext);
  if (!context) throw new Error("useI18n must be used within I18nProvider");
  return context;
}

export function LanguageSwitcher({ className = "" }: { className?: string }) {
  const { locale, setLocale, t } = useI18n();

  return (
    <Select<Locale>
      value={locale}
      onChange={(value) => setLocale(value)}
      options={locales.map((item) => ({ value: item, label: localeLabels[item] }))}
      prefix={<GlobalOutlined className="text-[#6b7280]" />}
      aria-label={t("common.language")}
      className={className}
      style={{ width: 150 }}
    />
  );
}



