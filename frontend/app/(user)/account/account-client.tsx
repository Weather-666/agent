"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Select } from "antd";
import { useI18n } from "@/lib/i18n";
import { toast } from "@/lib/toast";
import type { ApiError } from "@/lib/request";
import {
  getProfile,
  updateProfile,
  uploadAvatar,
  type PreferredLocale,
} from "@/lib/api/auth";
import { getCurrentSubscription } from "@/lib/api/plan-market";
import type { CurrentSubscriptionResponse } from "@/lib/api/plan-market";
import { getCurrentCredits } from "@/lib/api/credits";
import type { UserCredits } from "@/lib/api/credits";
import { getLibrarySpaces, type LibrarySpace, type StorageCategory } from "@/lib/api/library";
import type { MessageKey } from "@/lib/i18n/messages";

type AccountTab = "profile" | "subscription" | "seats" | "billing" | "storage";


function calcPct(used: number, total: number): { barWidth: string; label: string } {
  if (total <= 0 || used <= 0) return { barWidth: "0%", label: "0%" };
  const raw = Math.min(100, (used / total) * 100);
  const rounded = Math.round(raw);
  return {
    barWidth: `${raw}%`,
    label: rounded === 0 ? "< 1%" : `${rounded}%`,
  };
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(2)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

// 前端与后端 §5 约束保持一致，先本地拦截明显不合规的文件，减少无谓请求。
const AVATAR_ACCEPT = "image/jpeg,image/png,image/webp";
const AVATAR_ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp"];
const AVATAR_MAX_BYTES = 2 * 1024 * 1024;

// 把后端 §8 的业务错误码映射到已本地化的提示文案；未命中时回退到通用文案。
const AVATAR_ERROR_KEYS: Record<string, MessageKey> = {
  AVATAR_TOO_LARGE: "userPages.account.avatarTooLarge",
  AVATAR_UNSUPPORTED_TYPE: "userPages.account.avatarUnsupported",
  AVATAR_INVALID_IMAGE: "userPages.account.avatarInvalid",
  OBJECT_STORE_UNAVAILABLE: "userPages.account.avatarStoreUnavailable",
};

type AccountClientProps = {
  initialUsername: string;
  initialEmail: string;
};

function mapSubscriptionStatus(status: string): { label: string; className: string } {
  switch (status) {
    case "active":    return { label: "已激活",    className: "bg-[#eef8e8] text-[#4f8a2e]" };
    case "trialing":  return { label: "试用中",    className: "bg-[#e8f0fe] text-[#2b5f9e]" };
    case "past_due":  return { label: "逾期未续费", className: "bg-[#fff4e2] text-[#7a4b00]" };
    case "cancelled": return { label: "已取消",    className: "bg-[#f0eee9] text-[#6f6a64]" };
    case "expired":   return { label: "已过期",    className: "bg-[#f0eee9] text-[#6f6a64]" };
    default:          return { label: status,     className: "bg-[#f0eee9] text-[#6f6a64]" };
  }
}

function UserIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-[19px] w-[19px]" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 21a8 8 0 0 0-16 0M12 13a5 5 0 1 0 0-10 5 5 0 0 0 0 10Z" />
    </svg>
  );
}

function CardIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-[19px] w-[19px]" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 7h16v10H4zM8 11h8" />
    </svg>
  );
}

function ReceiptIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-[19px] w-[19px]" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M7 3h10v18l-2-1-2 1-2-1-2 1-2-1V3Z" />
      <path d="M10 8h4M10 12h4" />
    </svg>
  );
}

function StorageIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-[19px] w-[19px]" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 7h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2Z" />
      <path d="M7 12h10M8 16h8" />
    </svg>
  );
}

export default function AccountClient({ initialUsername, initialEmail }: AccountClientProps) {
  const router = useRouter();
  const { t, tList, setLocale } = useI18n();
  const [tab, setTab] = useState<AccountTab>("profile");

  // Seed the username / email captured at registration (read server-side from
  // cookies in page.tsx) so the first render already matches, then reconcile
  // against the authoritative profile from GET /api/v1/auth/me on mount.
  const [username, setUsername] = useState(initialUsername);
  const [email, setEmail] = useState(initialEmail);
  const [preferredLocale, setPreferredLocale] = useState<PreferredLocale | "">("");
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Subscription tab data — each loads independently so a failure in one doesn't hide the other
  const [subData, setSubData] = useState<CurrentSubscriptionResponse | null>(null);
  const [creditsData, setCreditsData] = useState<UserCredits | null>(null);
  const [subLoading, setSubLoading] = useState(false);
  const [subError, setSubError] = useState(false);
  const [creditsError, setCreditsError] = useState(false);
  const subFetchedRef = useRef(false);
  const creditsFetchedRef = useRef(false);
  const subFetchingRef = useRef(false);
  const creditsFetchingRef = useRef(false);

  // Storage tab data
  const [personalSpace, setPersonalSpace] = useState<LibrarySpace | null>(null);
  const [storageLoading, setStorageLoading] = useState(false);
  const [storageError, setStorageError] = useState(false);
  const storageFetchedRef = useRef(false);
  const storageFetchingRef = useRef(false);

  useEffect(() => {
    let ignore = false;

    getProfile()
      .then((profile) => {
        if (ignore) return;
        setUsername(profile.name ?? "");
        setEmail(profile.email ?? "");
        setPreferredLocale(profile.preferredLocale ?? "");
        setAvatarUrl(profile.avatarUrl ?? null);
      })
      .catch(() => {
        if (!ignore) toast.error(t("userPages.account.loadError"));
      });

    return () => {
      ignore = true;
    };
    // t is stable per locale; we only want this to run once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function fetchSubscription() {
    if (subFetchingRef.current) return;
    subFetchingRef.current = true;
    setSubError(false);
    setSubLoading(true);
    getCurrentSubscription()
      .then((sub) => {
        setSubData(sub);
        subFetchedRef.current = true;
      })
      .catch(() => {
        setSubError(true);
      })
      .finally(() => {
        subFetchingRef.current = false;
        setSubLoading(false);
      });
  }

  function fetchCredits() {
    if (creditsFetchingRef.current) return;
    creditsFetchingRef.current = true;
    setCreditsError(false);
    getCurrentCredits()
      .then((credits) => {
        setCreditsData(credits);
        creditsFetchedRef.current = true;
      })
      .catch(() => {
        setCreditsError(true);
      })
      .finally(() => {
        creditsFetchingRef.current = false;
      });
  }

  useEffect(() => {
    if (tab !== "subscription") return;
    if (!subFetchedRef.current && !subFetchingRef.current) fetchSubscription();
    if (!creditsFetchedRef.current && !creditsFetchingRef.current) fetchCredits();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  function fetchStorage() {
    if (storageFetchingRef.current) return;
    storageFetchingRef.current = true;
    setStorageLoading(true);
    setStorageError(false);

    getLibrarySpaces()
      .then((res) => {
        storageFetchingRef.current = false;
        const personal = res.items.find((s) => s.spaceType === "personal") ?? null;
        if (!personal || !personal.breakdown) {
          setStorageError(true);
          setPersonalSpace(null);
        } else {
          setPersonalSpace(personal);
          storageFetchedRef.current = true;
        }
        setStorageLoading(false);
      })
      .catch(() => {
        storageFetchingRef.current = false;
        setStorageError(true);
        setStorageLoading(false);
      });
  }

  useEffect(() => {
    if (tab !== "storage" || storageFetchedRef.current || storageFetchingRef.current) return;
    fetchStorage();

    return () => {
      // If we leave the tab mid-fetch, reset so we can re-fetch on return
      if (storageFetchingRef.current) {
        storageFetchingRef.current = false;
        setStorageLoading(false);
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  // Keep the identity mirror (localStorage + 30-day cookie) that the app shell
  // and the account page's server-side first render both read from.
  function syncNameCache(name: string) {
    window.localStorage.setItem("user_name", name);
    document.cookie = `user_name=${encodeURIComponent(name)}; Path=/; Max-Age=2592000; SameSite=Lax`;
  }

  function resolveAvatarError(error: ApiError) {
    const key = typeof error.code === "string" ? AVATAR_ERROR_KEYS[error.code] : undefined;
    return key ? t(key) : t("userPages.account.saveError");
  }

  async function handleSaveProfile() {
    const trimmedName = username.trim();
    if (!trimmedName) {
      toast.error(t("userPages.account.nameRequired"));
      return;
    }

    setSaving(true);
    try {
      const profile = await updateProfile({
        name: trimmedName,
        preferredLocale: preferredLocale || null,
      });
      setUsername(profile.name ?? trimmedName);
      setPreferredLocale(profile.preferredLocale ?? "");
      setAvatarUrl(profile.avatarUrl ?? null);
      syncNameCache(profile.name ?? trimmedName);
      // Saving a concrete locale preference also switches the live UI language.
      if (profile.preferredLocale) {
        setLocale(profile.preferredLocale);
      }
      toast.success(t("userPages.account.saveSuccess"));
    } catch (error) {
      toast.error(resolveAvatarError(error as ApiError));
    } finally {
      setSaving(false);
    }
  }

  async function handleAvatarSelected(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    // Allow re-selecting the same file later by clearing the input value.
    event.target.value = "";
    if (!file) return;

    if (!AVATAR_ALLOWED_TYPES.includes(file.type)) {
      toast.error(t("userPages.account.avatarUnsupported"));
      return;
    }
    if (file.size > AVATAR_MAX_BYTES) {
      toast.error(t("userPages.account.avatarTooLarge"));
      return;
    }

    setUploading(true);
    try {
      const profile = await uploadAvatar(file);
      setAvatarUrl(profile.avatarUrl ?? null);
      toast.success(t("userPages.account.avatarUpdated"));
    } catch (error) {
      toast.error(resolveAvatarError(error as ApiError));
    } finally {
      setUploading(false);
    }
  }

  const avatarInitial = (username || email).trim().slice(0, 1).toUpperCase() || "?";

  return (
    <section className="mx-auto min-h-screen w-full max-w-[1024px] px-4 pb-10 pt-10 sm:px-6 lg:px-8">
      <div className="relative rounded-[14px] bg-white px-[34px] pb-9 pt-[58px] text-[#252930] shadow-[0_16px_34px_rgba(20,28,42,0.1)]">
        <button
          className="absolute right-6 top-6 grid h-[34px] w-[34px] place-items-center rounded-[8px] hover:bg-[#f3f4f7]"
          type="button"
          aria-label={t("userPages.common.close")}
          onClick={() => router.back()}
        >
          <svg viewBox="0 0 24 24" className="h-[22px] w-[22px]" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>

        <h1 className="mx-auto mb-6 max-w-[944px] text-[22px] font-bold">{t("userPages.account.title")}</h1>

        <div className="mx-auto grid max-w-[944px] grid-cols-1 gap-6 lg:grid-cols-[224px_1fr]">
          <nav className="h-max rounded-[14px] border border-[#deded9] bg-[#fbfaf8] p-1.5" aria-label={t("userPages.account.settings")}>
            <button
              type="button"
              onClick={() => setTab("profile")}
              className={`flex h-[42px] w-full items-center gap-3 rounded-[10px] px-[13px] text-left text-[14px] ${
                tab === "profile" ? "bg-[#f1f1ef] text-[#252930]" : "text-[#85858a]"
              }`}
            >
              <UserIcon />
              {t("userPages.account.profile")}
              <span className="ml-auto text-[22px]">›</span>
            </button>
            <button
              type="button"
              onClick={() => setTab("subscription")}
              className={`flex h-[42px] w-full items-center gap-3 rounded-[10px] px-[13px] text-left text-[14px] ${
                tab === "subscription" ? "bg-[#f1f1ef] text-[#252930]" : "text-[#85858a]"
              }`}
            >
              <CardIcon />
              {t("userPages.account.subscription")}
            </button>
            <button
              type="button"
              onClick={() => setTab("storage")}
              className={`flex h-[42px] w-full items-center gap-3 rounded-[10px] px-[13px] text-left text-[14px] ${
                tab === "storage" ? "bg-[#f1f1ef] text-[#252930]" : "text-[#85858a]"
              }`}
            >
              <StorageIcon />
              {t("userPages.account.storage.title")}
            </button>
            {/* billing tab hidden — feature not yet implemented */}
            {/* <button
              type="button"
              onClick={() => setTab("billing")}
              className={`flex h-[42px] w-full items-center gap-3 rounded-[10px] px-[13px] text-left text-[14px] ${
                tab === "billing" ? "bg-[#f1f1ef] text-[#252930]" : "text-[#85858a]"
              }`}
            >
              <ReceiptIcon />
              {t("userPages.account.billing")}
            </button> */}
          </nav>

          <div className="min-h-[500px] rounded-[14px] border border-[#deded9] bg-white px-7 py-[26px]">
            {tab === "profile" ? (
              <section>
                <h2 className="mb-[22px] text-[22px] font-semibold">{t("userPages.account.profileInfo")}</h2>
                <label className="mb-2 block text-[14px] text-[#777d88]">{t("userPages.account.avatar")}</label>
                <div className="mb-[18px] flex items-center gap-4">
                  {avatarUrl ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={avatarUrl}
                      alt={t("userPages.account.avatar")}
                      className="h-16 w-16 rounded-full object-cover"
                    />
                  ) : (
                    <span className="grid h-16 w-16 place-items-center rounded-full bg-[#e83b18] text-[24px] text-white">{avatarInitial}</span>
                  )}
                  <button
                    type="button"
                    disabled={uploading}
                    onClick={() => fileInputRef.current?.click()}
                    className="h-[38px] rounded-[8px] border border-[#e2ddd5] bg-white px-4 text-[14px] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {uploading ? t("userPages.account.avatarUploading") : t("userPages.account.changeAvatar")}
                  </button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept={AVATAR_ACCEPT}
                    className="hidden"
                    onChange={handleAvatarSelected}
                  />
                </div>

                <label className="mb-2 mt-4 block text-[14px] text-[#777d88]">{t("userPages.account.username")}</label>
                <input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="h-[46px] w-full rounded-[9px] bg-[#f3f3f2] px-4 text-[15px] outline-none"
                />

                <label className="mb-2 mt-4 block text-[14px] text-[#777d88]">{t("userPages.account.email")}</label>
                <input
                  value={email}
                  readOnly
                  className="h-[46px] w-full rounded-[9px] bg-[#f3f3f2] px-4 text-[15px] text-[#6b7280] outline-none"
                />

                <label className="mb-2 mt-4 block text-[14px] text-[#777d88]">{t("userPages.account.language")}</label>
                <Select
                  value={preferredLocale}
                  onChange={(value) => setPreferredLocale(value as PreferredLocale | "")}
                  style={{ width: '100%', height: 46 }}
                  options={[
                    { value: "", label: t("userPages.account.languageFollowSystem") },
                    { value: "zh-CN", label: "简体中文" },
                    { value: "en-US", label: "English" },
                  ]}
                />

                <button
                  type="button"
                  disabled={saving}
                  onClick={handleSaveProfile}
                  className="mt-5 h-11 rounded-[9px] bg-[#111] px-6 text-[15px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {saving ? t("userPages.account.saving") : t("userPages.account.save")}
                </button>
              </section>
            ) : null}

            {tab === "subscription" ? (
              <section>
                <h2 className="mb-2 text-[22px] font-semibold">{t("userPages.account.mySubscription")}</h2>
                <p className="text-[14px] text-[#706a63]">{t("userPages.account.activeSubscriptions")}</p>

                {subLoading ? (
                  <div className="mt-6 flex min-h-[100px] items-center justify-center rounded-[10px] border border-[#e4ded7] bg-white">
                    <p className="text-[14px] text-[#8a8f99]">加载中...</p>
                  </div>
                ) : subError ? (
                  <div className="mt-6 flex items-center justify-between rounded-[10px] border border-[#e4ded7] bg-white p-5">
                    <p className="text-[14px] text-[#8a8580]">订阅信息加载失败</p>
                    <button
                      type="button"
                      onClick={() => { subFetchedRef.current = false; fetchSubscription(); }}
                      className="h-[34px] rounded-[8px] border border-[#e2ddd5] bg-white px-4 text-[13px] text-[#25221f] hover:bg-[#f7f5f2]"
                    >
                      重试
                    </button>
                  </div>
                ) : subData ? (
                  <div className="mt-6">
                    <article className="relative rounded-[10px] border border-[#e4ded7] border-l-[3px] border-l-[#ff9900] bg-white p-5">
                      <div className="flex items-start justify-between">
                        <span className="rounded-[8px] bg-[#fff4e2] px-[9px] py-1 text-[12px] text-[#7a4b00]">
                          {subData.plan.typeLabel || t("userPages.subscribe.personal")}
                        </span>
                        {(() => {
                          const s = mapSubscriptionStatus(subData.subscription.status);
                          return (
                            <span className={`rounded-[12px] px-[10px] py-1 text-[12px] ${s.className}`}>
                              {s.label}
                            </span>
                          );
                        })()}
                      </div>

                      <h3 className="mb-1 mt-[10px] text-[18px] font-bold text-[#171512]">{subData.plan.name}</h3>
                      {subData.plan.description && (
                        <p className="mb-2 text-[14px] text-[#6f6a64]">{subData.plan.description}</p>
                      )}

                      {subData.subscription.currentPeriodEnd && (
                        <div className="mt-3 flex items-center justify-between border-t border-[#eee9e3] pt-3 text-[13px] text-[#6f6a64]">
                          <span>{t("userPages.account.expiryDate")}</span>
                          <strong className="text-[#25221f]" style={{ fontWeight: 560 }}>
                            {new Date(subData.subscription.currentPeriodEnd).toLocaleDateString("zh-CN")}
                          </strong>
                        </div>
                      )}

                      {/* 本月积分用量 — 无论余额是否为零都展示 */}
                      {creditsData ? (
                        <div className="my-[14px]">
                          {(() => {
                            const cp = calcPct(creditsData.deductedCredits, creditsData.monthlyCreditLimit);
                            return (
                              <>
                                <div className="mb-2 flex items-center justify-between text-[13px] text-[#25221f]">
                                  <strong style={{ fontWeight: 560 }}>本月积分额度</strong>
                                  {creditsData.monthlyCreditLimit > 0 && (
                                    <em className="not-italic" style={{ fontWeight: 560 }}>{cp.label}</em>
                                  )}
                                </div>
                                <i className="block h-[5px] overflow-hidden rounded-full bg-[#ece9e4]">
                                  <b
                                    className="block h-full rounded-full bg-[#27b36a]"
                                    style={{ width: cp.barWidth }}
                                  />
                                </i>
                                <p className="mt-2 text-[12px] text-[#6f6a64]">
                                  {creditsData.monthlyCreditLimit > 0
                                    ? `${creditsData.deductedCredits.toLocaleString()} / ${creditsData.monthlyCreditLimit.toLocaleString()}`
                                    : `已用 ${creditsData.deductedCredits.toLocaleString()}`}
                                  <span className={`ml-2 ${creditsData.remainingCredits > 0 ? "text-[#4f8a2e]" : "text-[#8a8580]"}`}>
                                    剩余 {creditsData.remainingCredits.toLocaleString()}
                                  </span>
                                </p>
                                {!creditsData.enforcementEnabled && (
                                  <p className="mt-1 text-[11px] text-[#8a8f99]">积分限额暂未强制执行</p>
                                )}
                              </>
                            );
                          })()}
                        </div>
                      ) : creditsError ? (
                        <div className="my-[14px] flex items-center justify-between rounded-[8px] border border-[#e4ded7] px-3 py-2">
                          <p className="text-[13px] text-[#8a8580]">积分信息加载失败</p>
                          <button
                            type="button"
                            onClick={() => { creditsFetchedRef.current = false; fetchCredits(); }}
                            className="text-[13px] text-[#2b5f9e] hover:underline"
                          >
                            重试
                          </button>
                        </div>
                      ) : null}

                      <div className="mt-4 flex flex-wrap gap-2.5">
                        <button type="button" onClick={() => router.push("/subscribe")} className="h-[38px] rounded-[8px] border border-[#e2ddd5] bg-white px-4 text-[14px] text-[#25221f]">{t("userPages.account.changePlan")}</button>
                      </div>
                    </article>
                  </div>
                ) : (
                  <div className="mt-6 rounded-[10px] border border-[#e4ded7] bg-white p-5 text-[14px] text-[#6f6a64]">
                    暂无订阅信息
                  </div>
                )}

                {/* 积分独立展示区（订阅加载失败但积分成功时） */}
                {subError && creditsData && (() => {
                  const cp = calcPct(creditsData.deductedCredits, creditsData.monthlyCreditLimit);
                  return (
                    <div className="mt-4 rounded-[10px] border border-[#e4ded7] bg-white p-5">
                      <div className="mb-2 flex items-center justify-between text-[13px] text-[#25221f]">
                        <strong style={{ fontWeight: 560 }}>本月积分额度</strong>
                        {creditsData.monthlyCreditLimit > 0 && (
                          <em className="not-italic" style={{ fontWeight: 560 }}>{cp.label}</em>
                        )}
                      </div>
                      <i className="block h-[5px] overflow-hidden rounded-full bg-[#ece9e4]">
                        <b
                          className="block h-full rounded-full bg-[#27b36a]"
                          style={{ width: cp.barWidth }}
                        />
                      </i>
                      <p className="mt-2 text-[12px] text-[#6f6a64]">
                        {creditsData.monthlyCreditLimit > 0
                          ? `${creditsData.deductedCredits.toLocaleString()} / ${creditsData.monthlyCreditLimit.toLocaleString()}`
                          : `已用 ${creditsData.deductedCredits.toLocaleString()}`}
                        <span className={`ml-2 ${creditsData.remainingCredits > 0 ? "text-[#4f8a2e]" : "text-[#8a8580]"}`}>
                          剩余 {creditsData.remainingCredits.toLocaleString()}
                        </span>
                      </p>
                    </div>
                  );
                })()}
                {subError && !creditsData && creditsError && (
                  <div className="mt-4 flex items-center justify-between rounded-[10px] border border-[#e4ded7] bg-white p-5">
                    <p className="text-[14px] text-[#8a8580]">积分信息加载失败</p>
                    <button
                      type="button"
                      onClick={() => { creditsFetchedRef.current = false; fetchCredits(); }}
                      className="h-[34px] rounded-[8px] border border-[#e2ddd5] bg-white px-4 text-[13px] text-[#25221f] hover:bg-[#f7f5f2]"
                    >
                      重试
                    </button>
                  </div>
                )}
              </section>
            ) : null}

            {tab === "seats" ? (
              <section>
                <div className="mb-6 flex items-start gap-3">
                  <button type="button" onClick={() => setTab("subscription")} className="grid h-8 w-8 shrink-0 place-items-center rounded-[8px] text-[#1f1b1d] hover:bg-[#f4f5f7]">
                    <svg viewBox="0 0 24 24" className="h-[22px] w-[22px]" fill="none" stroke="currentColor" strokeWidth="2"><path d="m15 18-6-6 6-6" /></svg>
                  </button>
                  <div>
                    <h2 className="mb-1 text-[22px] font-semibold">{t("userPages.account.seats")}</h2>
                    <p className="text-[14px] text-[#706a63]">{t("userPages.account.seatsRemaining")}</p>
                  </div>
                </div>

                {/* 席位概览卡片 */}
                <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
                  <div className="rounded-[8px] bg-[#f6f4ef] px-4 py-[14px]">
                    <span className="block text-[12px] text-[#5f5a54]">{t("userPages.account.seatUsageLabel")}</span>
                    <strong className="my-2 block text-[22px] text-[#111]" style={{ fontWeight: 620 }}>
                      {t("userPages.account.seatUsageValue")}<small className="ml-0.5 text-[13px] font-medium text-[#111]">{t("userPages.account.seatUsageSuffix")}</small>
                    </strong>
                    <i className="block h-[5px] overflow-hidden rounded-full bg-[#ece9e4]">
                      <b className="block h-full w-[60%] rounded-full bg-[#2f80ed]" />
                    </i>
                  </div>
                  <div className="rounded-[8px] bg-[#f6f4ef] px-4 py-[14px]">
                    <span className="block text-[12px] text-[#5f5a54]">{t("userPages.account.teamMonthlyChats")}</span>
                    <strong className="my-2 block text-[22px] text-[#111]" style={{ fontWeight: 620 }}>
                      {t("userPages.account.chatUsageValue")}<small className="ml-0.5 text-[13px] font-medium text-[#111]">{t("userPages.account.chatUsageSuffix")}</small>
                    </strong>
                    <i className="block h-[5px] overflow-hidden rounded-full bg-[#ece9e4]">
                      <b className="block h-full w-[37%] rounded-full bg-[#2f80ed]" />
                    </i>
                  </div>
                  <div className="rounded-[8px] bg-[#f6f4ef] px-4 py-[14px]">
                    <span className="block text-[12px] text-[#5f5a54]">{t("userPages.account.teamMonthlyTokens")}</span>
                    <strong className="my-2 block text-[22px] text-[#111]" style={{ fontWeight: 620 }}>
                      {t("userPages.account.tokenUsageValue")}<small className="ml-0.5 text-[13px] font-medium text-[#111]">{t("userPages.account.tokenUsageSuffix")}</small>
                    </strong>
                    <i className="block h-[5px] overflow-hidden rounded-full bg-[#ece9e4]">
                      <b className="block h-full w-[42%] rounded-full bg-[#ff9900]" />
                    </i>
                  </div>
                  <div className="rounded-[8px] bg-[#f6f4ef] px-4 py-[14px]">
                    <span className="block text-[12px] text-[#5f5a54]">{t("userPages.account.totalExpertCalls")}</span>
                    <strong className="my-2 block text-[22px] text-[#111]" style={{ fontWeight: 620 }}>
                      {t("userPages.account.expertCallValue")}<small className="ml-0.5 text-[13px] font-medium text-[#111]">{t("userPages.account.expertCallUnit")}</small>
                    </strong>
                    <i className="block h-[5px] overflow-hidden rounded-full bg-[#ece9e4]">
                      <b className="block h-full w-[72%] rounded-full bg-[#232f3e]" />
                    </i>
                  </div>
                </div>

                {/* 邀请新成员 */}
                <h3 className="mb-2.5 text-[16px] font-semibold text-[#1f1b1d]">{t("userPages.account.inviteMember")}</h3>
                <div className="grid grid-cols-1 gap-2 md:grid-cols-[1fr_150px_132px]">
                  <input aria-label={t("userPages.account.memberEmail")} className="h-[38px] rounded-[8px] border border-[#e2ddd5] bg-white px-3 text-[14px] text-[#25221f]" placeholder={t("userPages.account.inputEmail")} />
                  <Select
                    aria-label={t("userPages.account.memberRole")}
                    defaultValue="member"
                    style={{ width: '100%', height: 38 }}
                    options={[
                      { value: "member", label: t("userPages.account.member") },
                      { value: "admin", label: t("userPages.account.admin") },
                    ]}
                  />
                  <button type="button" className="h-[38px] rounded-[8px] bg-[#111] px-4 text-[14px] text-white">{t("userPages.account.sendInvite")}</button>
                </div>

                {/* 团队成员表格 */}
                <h3 className="mb-2.5 mt-5 text-[16px] font-semibold text-[#1f1b1d]">
                  {t("userPages.account.teamMembers")} <span className="font-normal text-[#6f6a64]">{t("userPages.account.peopleCount")}</span>
                </h3>
                <div className="overflow-hidden rounded-[10px] border border-[#e4ded7] bg-white">
                  {/* 表头 */}
                  <div className="grid min-h-[34px] items-center gap-3 bg-[#f3f1ec] px-[14px] text-[12px] font-[560] text-[#4f4943]"
                       style={{ gridTemplateColumns: "38px minmax(166px, 0.95fr) 104px minmax(230px, 1.15fr) 168px" }}>
                    <span className="col-span-2">{t("userPages.account.member")}</span>
                    <span>{t("userPages.account.joinDate")}</span>
                    <span>{t("userPages.account.monthlyUsageHeader")}</span>
                    <span>{t("userPages.account.action")}</span>
                  </div>

                  {/* 成员行 1 — 管理员（本人） */}
                  <div className="grid min-h-[58px] items-center gap-3 border-b border-[#eee9e3] px-[14px] py-[10px] text-[13px]"
                       style={{ gridTemplateColumns: "38px minmax(166px, 0.95fr) 104px minmax(230px, 1.15fr) 168px" }}>
                    <span className="grid h-[34px] w-[34px] place-items-center rounded-full bg-[#f0eaf8] text-[12px] font-bold text-[#6a5796]">
                      {t("userPages.account.member1Name").charAt(0)}
                    </span>
                    <div className="min-w-0">
                      <strong className="block text-[14px] text-[#1f1b1d]">{t("userPages.account.member1Name")}（{t("userPages.account.admin").includes("管") ? "我" : "me"}）</strong>
                      <small className="block text-[12px] text-[#6f6a64]">wanglei@memo-labs.com</small>
                      <em className="mt-1 inline-flex rounded-[10px] bg-[#f5f3ef] px-2 py-0.5 text-[12px] not-italic text-[#6f6a64]">{t("userPages.account.admin")}</em>
                    </div>
                    <span className="text-[13px] text-[#5c5650]">{t("userPages.account.member1JoinDate")}</span>
                    <div className="grid gap-[7px] text-[12px] text-[#25221f]">
                      <span>{t("userPages.account.member1Usage")}</span>
                      <i className="block h-[5px] overflow-hidden rounded-full bg-[#ece9e4]">
                        <b className="block h-full w-[46%] rounded-full bg-[#2f80ed]" />
                      </i>
                    </div>
                    <button type="button" disabled className="min-h-[34px] w-full rounded-[8px] border border-[#e2ddd5] bg-white px-3 text-[#b5b0aa]">—</button>
                  </div>

                  {/* 成员行 2 — 普通成员（已激活） */}
                  <div className="grid min-h-[58px] items-center gap-3 border-b border-[#eee9e3] px-[14px] py-[10px] text-[13px]"
                       style={{ gridTemplateColumns: "38px minmax(166px, 0.95fr) 104px minmax(230px, 1.15fr) 168px" }}>
                    <span className="grid h-[34px] w-[34px] place-items-center rounded-full bg-[#e7f5ec] text-[12px] font-bold text-[#348857]">
                      {t("userPages.account.member2Name").charAt(0)}
                    </span>
                    <div className="min-w-0">
                      <strong className="block text-[14px] text-[#1f1b1d]">{t("userPages.account.member2Name")}</strong>
                      <small className="block text-[12px] text-[#6f6a64]">zhangyu@memo-labs.com</small>
                      <em className="mt-1 inline-flex rounded-[10px] bg-[#f5f3ef] px-2 py-0.5 text-[12px] not-italic text-[#6f6a64]">{t("userPages.account.member")}</em>
                    </div>
                    <span className="text-[13px] text-[#5c5650]">{t("userPages.account.member2JoinDate")}</span>
                    <div className="grid gap-[7px] text-[12px] text-[#25221f]">
                      <span>{t("userPages.account.member2Usage")}</span>
                      <i className="block h-[5px] overflow-hidden rounded-full bg-[#ece9e4]">
                        <b className="block h-full w-[62%] rounded-full bg-[#2f80ed]" />
                      </i>
                    </div>
                    <div className="grid grid-cols-[1fr_56px] gap-2">
                      <button type="button" className="min-h-[34px] whitespace-nowrap rounded-[8px] border border-[#e2ddd5] bg-white px-3 text-[13px] text-[#25221f]">{t("userPages.account.makeAdmin")}</button>
                      <button type="button" className="min-h-[34px] rounded-[8px] border border-[#e2ddd5] bg-white px-3 text-[13px] text-[#25221f]">{t("userPages.account.remove")}</button>
                    </div>
                  </div>

                  {/* 成员行 3 — 普通成员（待接受） */}
                  <div className="grid min-h-[58px] items-center gap-3 border-b border-[#eee9e3] px-[14px] py-[10px] text-[13px]"
                       style={{ gridTemplateColumns: "38px minmax(166px, 0.95fr) 104px minmax(230px, 1.15fr) 168px" }}>
                    <span className="grid h-[34px] w-[34px] place-items-center rounded-full bg-[#e5f7f0] text-[12px] font-bold text-[#248765]">
                      {t("userPages.account.member3Name").charAt(0)}
                    </span>
                    <div className="min-w-0">
                      <strong className="block text-[14px] text-[#1f1b1d]">{t("userPages.account.member3Name")}</strong>
                      <small className="block text-[12px] text-[#6f6a64]">lixin@memo-labs.com</small>
                      <em className="mt-1 inline-flex rounded-[10px] bg-[#f5f3ef] px-2 py-0.5 text-[12px] not-italic text-[#6f6a64]">{t("userPages.account.member")}</em>
                    </div>
                    <span className="text-[13px] text-[#5c5650]">{t("userPages.account.member3JoinDate")}</span>
                    <div className="grid gap-[7px] text-[12px] text-[#25221f]">
                      <span>{t("userPages.account.member3Usage")}</span>
                      <i className="block h-[5px] overflow-hidden rounded-full bg-[#ece9e4]">
                        <b className="block h-full w-[34%] rounded-full bg-[#2f80ed]" />
                      </i>
                    </div>
                    <div className="grid grid-cols-[1fr_56px] gap-2">
                      <button type="button" className="min-h-[34px] whitespace-nowrap rounded-[8px] border border-[#e2ddd5] bg-white px-3 text-[13px] text-[#25221f]">{t("userPages.account.makeAdmin")}</button>
                      <button type="button" className="min-h-[34px] rounded-[8px] border border-[#e2ddd5] bg-white px-3 text-[13px] text-[#25221f]">{t("userPages.account.remove")}</button>
                    </div>
                  </div>

                  {/* 成员行 4 — 邀请中 */}
                  <div className="grid min-h-[58px] items-center gap-3 px-[14px] py-[10px] text-[13px]"
                       style={{ gridTemplateColumns: "38px minmax(166px, 0.95fr) 104px minmax(230px, 1.15fr) 168px" }}>
                    <span className="grid h-[34px] w-[34px] place-items-center rounded-full bg-[#fff2df] text-[12px] font-bold text-[#9a6931]">
                      {t("userPages.account.member4Name").charAt(0)}
                    </span>
                    <div className="min-w-0">
                      <strong className="block text-[14px] text-[#1f1b1d]">{t("userPages.account.member4Name")}</strong>
                      <small className="block text-[12px] text-[#6f6a64]">zhaoliu@corp.com</small>
                      <em className="mt-1 inline-flex rounded-[10px] bg-[#f5f3ef] px-2 py-0.5 text-[12px] not-italic text-[#6f6a64]">{t("userPages.account.member")}</em>
                    </div>
                    <span className="text-[13px] text-[#5c5650]">{t("userPages.account.member4JoinDate")}</span>
                    <div className="text-[12px] text-[#8a8580]">—</div>
                    <button type="button" className="min-h-[34px] w-full whitespace-nowrap rounded-[8px] border border-[#e2ddd5] bg-white px-3 text-[13px] text-[#25221f]">{t("userPages.account.revoke")}</button>
                  </div>
                </div>

                {/* 席位警告 */}
                <div className="mt-3 rounded-[8px] bg-[#fff0d3] px-[14px] py-3 text-[12px] text-[#7a4b00]">
                  {t("userPages.account.seatWarning")}
                </div>
              </section>
            ) : null}

            {tab === "billing" ? (
              <section>
                <h2 className="mb-[22px] text-[22px] font-semibold">{t("userPages.account.billing")}</h2>
                <div className="overflow-hidden rounded-[12px] border border-[#e3e5ea] bg-[#fafbfc]">
                  <div className="grid grid-cols-[1.6fr_1fr_0.8fr_0.8fr_0.8fr] gap-2 border-b border-[#eceff3] px-4 py-3 text-[12px] text-[#737a86]">
                    <span>{t("userPages.account.date")}</span><span>{t("userPages.account.category")}</span><span>{t("userPages.account.amount")}</span><span>{t("userPages.account.status")}</span><span>{t("userPages.account.invoice")}</span>
                  </div>
                  <div className="grid grid-cols-[1.6fr_1fr_0.8fr_0.8fr_0.8fr] items-center gap-2 border-b border-[#eceff3] px-4 py-3 text-[13px]">
                    <span>2026-06-28 09:30:00</span><span>{t("userPages.account.subscriptionCategory")}</span><span>¥106</span><span><em className="not-italic text-[#2e7d32]">Paid</em></span><button type="button" className="text-left text-[#2b5f9e]">{t("userPages.common.download")}</button>
                  </div>
                  <div className="grid grid-cols-[1.6fr_1fr_0.8fr_0.8fr_0.8fr] items-center gap-2 px-4 py-3 text-[13px]">
                    <span>2027-05-28 10:00:00</span><span>{t("userPages.account.businessCategory")}</span><span>1,200 USD</span><span><em className="not-italic text-[#2e7d32]">Paid</em></span><button type="button" className="text-left text-[#2b5f9e]">{t("userPages.common.download")}</button>
                  </div>
                  <p className="border-t border-[#eceff3] px-4 py-3 text-[12px] text-[#8a8f99]">{t("userPages.account.noMoreData")}</p>
                </div>
              </section>
            ) : null}

            {tab === "storage" ? (
              <section>
                <h2 className="mb-[22px] text-[22px] font-semibold">{t("userPages.account.storage.title")}</h2>

                {storageLoading ? (
                  <div className="flex min-h-[160px] items-center justify-center rounded-[10px] border border-[#e4ded7]">
                    <p className="text-[14px] text-[#8a8f99]">{t("userPages.account.storage.loading")}</p>
                  </div>
                ) : storageError || !personalSpace ? (
                  <div className="flex min-h-[160px] flex-col items-center justify-center gap-3 rounded-[10px] border border-[#e4ded7]">
                    <p className="text-[14px] text-[#8a8580]">{t("userPages.account.storage.loadFailed")}</p>
                    <button
                      type="button"
                      onClick={() => { storageFetchedRef.current = false; fetchStorage(); }}
                      className="h-[34px] rounded-[8px] border border-[#e2ddd5] bg-white px-4 text-[13px] text-[#25221f] hover:bg-[#f7f5f2]"
                    >
                      {t("userPages.account.storage.retry")}
                    </button>
                  </div>
                ) : (() => {
                  const { usedBytes, quotaBytes, remainingBytes, reservedBytes, breakdown } = personalSpace;
                  if (!breakdown) return null;
                  const sp = calcPct(usedBytes, quotaBytes);
                  const pctRaw = quotaBytes > 0 ? Math.min(100, (usedBytes / quotaBytes) * 100) : 0;
                  const isNearFull = pctRaw >= 90;

                  const permFiles = breakdown.permanent;
                  const tmpFiles = breakdown.temporary;
                  const totalFileCount = permFiles.fileCount + tmpFiles.fileCount;
                  const totalFileBytes = permFiles.fileBytes + tmpFiles.fileBytes;
                  const totalImageCount = permFiles.imageCount + tmpFiles.imageCount;
                  const totalImageBytes = permFiles.imageBytes + tmpFiles.imageBytes;

                  return (
                    <>
                      {/* 总用量概览 */}
                      <div className="mb-6 rounded-[10px] border border-[#e4ded7] bg-[#fafaf8] p-5">
                        <p className="mb-3 text-[15px] font-[560] text-[#1f1b1d]">
                          {t("userPages.account.storage.usedOf", { used: formatBytes(usedBytes), quota: formatBytes(quotaBytes) })}
                        </p>
                        <i className="block h-[6px] overflow-hidden rounded-full bg-[#ece9e4]">
                          <b
                            className="block h-full rounded-full transition-[width]"
                            style={{
                              width: sp.barWidth,
                              backgroundColor: isNearFull ? "#e8563a" : "#2f80ed",
                            }}
                          />
                        </i>
                        <p className={`mt-2 text-[12px] ${isNearFull ? "text-[#9d3b31]" : "text-[#8a8580]"}`}>
                          {sp.label} {t("userPages.account.storage.used")} · {t("userPages.account.storage.available")} {formatBytes(remainingBytes)}
                          {isNearFull && <span className="ml-2">· {t("userPages.account.storage.nearFull")}</span>}
                        </p>
                        {reservedBytes > 0 && (
                          <p className="mt-1 text-[12px] text-[#8a8580]">
                            {t("userPages.account.storage.uploading", { size: formatBytes(reservedBytes) })}
                          </p>
                        )}
                      </div>

                      {/* 分类统计 */}
                      <h3 className="mb-3 text-[16px] font-semibold text-[#1f1b1d]">{t("userPages.account.storage.categories")}</h3>
                      <div className="mb-6 overflow-hidden rounded-[10px] border border-[#e4ded7]">
                        {/* 文件 */}
                        <div className="border-b border-[#eee9e3] px-5 py-[14px]">
                          <div className="flex items-start justify-between">
                            <div>
                              <strong className="block text-[14px] text-[#1f1b1d]">
                                {t("userPages.account.storage.files")} <span className="font-normal text-[#8a8580]">{t("userPages.account.storage.count", { count: totalFileCount })}</span>
                              </strong>
                              <em className="mt-0.5 block text-[12px] not-italic text-[#8a8580]">{formatBytes(totalFileBytes)}</em>
                            </div>
                            <button
                              type="button"
                              onClick={() => router.push("/library")}
                              className="mt-0.5 text-[12px] text-[#2b5f9e] hover:underline"
                            >
                              {t("userPages.account.storage.manage")}
                            </button>
                          </div>
                          {(permFiles.fileCount > 0 || tmpFiles.fileCount > 0) && (
                            <div className="mt-2 flex gap-4 text-[12px] text-[#8a8580]">
                              <span>{t("userPages.account.storage.permanent")} {t("userPages.account.storage.count", { count: permFiles.fileCount })} · {formatBytes(permFiles.fileBytes)}</span>
                              <span>{t("userPages.account.storage.temporary")} {t("userPages.account.storage.count", { count: tmpFiles.fileCount })} · {formatBytes(tmpFiles.fileBytes)}</span>
                            </div>
                          )}
                        </div>
                        {/* 图片 */}
                        <div className="px-5 py-[14px]">
                          <div className="flex items-start justify-between">
                            <div>
                              <strong className="block text-[14px] text-[#1f1b1d]">
                                {t("userPages.account.storage.images")} <span className="font-normal text-[#8a8580]">{t("userPages.account.storage.count", { count: totalImageCount })}</span>
                              </strong>
                              <em className="mt-0.5 block text-[12px] not-italic text-[#8a8580]">{formatBytes(totalImageBytes)}</em>
                            </div>
                            <button
                              type="button"
                              onClick={() => router.push("/library")}
                              className="mt-0.5 text-[12px] text-[#2b5f9e] hover:underline"
                            >
                              {t("userPages.account.storage.manage")}
                            </button>
                          </div>
                          {(permFiles.imageCount > 0 || tmpFiles.imageCount > 0) && (
                            <div className="mt-2 flex gap-4 text-[12px] text-[#8a8580]">
                              <span>{t("userPages.account.storage.permanent")} {t("userPages.account.storage.count", { count: permFiles.imageCount })} · {formatBytes(permFiles.imageBytes)}</span>
                              <span>{t("userPages.account.storage.temporary")} {t("userPages.account.storage.count", { count: tmpFiles.imageCount })} · {formatBytes(tmpFiles.imageBytes)}</span>
                            </div>
                          )}
                        </div>
                      </div>
                    </>
                  );
                })()}
              </section>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}
