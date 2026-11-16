"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useI18n, type Translate } from "@/lib/i18n";
import { toast } from "@/lib/toast";
import { getPlanMarketPlans, getCurrentSubscription, upgradeSubscription } from "@/lib/api/plan-market";
import type { CurrentSubscriptionResponse } from "@/lib/api/plan-market";
import type { ApiError } from "@/lib/request";
import type { Plan, PlanPrice } from "@/lib/api/plans";
import { getProfile } from "@/lib/api/auth";

type PlanTab = "personal" | "business";

function classifyPlan(plan: Plan): PlanTab {
  return plan.code.toLowerCase().includes("business") ? "business" : "personal";
}

function getDisplayPrice(plan: Plan): PlanPrice | null {
  const enabled = plan.prices.filter((price) => price.isEnabled);
  return enabled.find((price) => price.billingPeriod === "sales") ?? enabled.find((price) => price.billingPeriod === "monthly") ?? enabled.find((price) => price.billingPeriod === "yearly") ?? enabled.find((price) => price.billingPeriod === "free") ?? null;
}

function formatPriceAmount(price: PlanPrice, fractionDigits: 0 | 2, locale: string): string {
  const currency = price.currency?.trim().toUpperCase() || "CNY";
  const amount = price.amountCents / 100;

  try {
    const number = new Intl.NumberFormat(locale, {
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    }).format(amount);
    return currency === "USD" ? `US$${number}` : `¥${number}`;
  } catch {
    // The API validates currency when prices are saved, but keep the customer-facing
    // page usable if legacy data contains an unsupported currency code.
    return `${currency} ${amount.toFixed(fractionDigits)}`;
  }
}

function PriceDisplay({ price, t, locale }: { price: PlanPrice | null; t: Translate; locale: string }) {
  if (!price) return <span className="text-[22px] font-normal">{t("userPages.subscribe.priceNotConfigured")}</span>;
  if (price.billingPeriod === "free") {
    return <>{formatPriceAmount(price, 0, locale)} <span className="text-[13px] font-normal text-[#6f7683]">{t("userPages.subscribe.perMonth")}</span></>;
  }
  if (price.billingPeriod === "monthly") {
    return <>{formatPriceAmount(price, 0, locale)} <span className="text-[13px] font-normal text-[#6f7683]">{t("userPages.subscribe.perMonth")}</span></>;
  }
  if (price.billingPeriod === "yearly") {
    return <>{formatPriceAmount(price, 0, locale)} <span className="text-[13px] font-normal text-[#6f7683]">{t("userPages.subscribe.perYear")}</span></>;
  }
  return <span className="text-[22px] font-normal">{t("userPages.subscribe.contactSales")}</span>;
}

function formatCheckoutPrice(price: PlanPrice | null, t: Translate, locale: string): string {
  if (!price) return t("userPages.subscribe.priceNotConfigured");
  if (price.billingPeriod === "sales") return t("userPages.subscribe.contactSales");
  return formatPriceAmount(price, 2, locale);
}

function getPricePeriodLabel(price: PlanPrice | null, t: Translate): string {
  if (!price || price.billingPeriod === "free" || price.billingPeriod === "monthly") return t("userPages.subscribe.monthlyPeriod");
  if (price.billingPeriod === "yearly") return t("userPages.subscribe.yearlyPeriod");
  return "";
}

export default function SubscribePage() {
  const router = useRouter();
  const { t, tList, locale } = useI18n();
  const [tab, setTab] = useState<PlanTab>("personal");
  const [plans, setPlans] = useState<Plan[]>([]);
  const [currentSub, setCurrentSub] = useState<CurrentSubscriptionResponse | null>(null);
  const [loading, setLoading] = useState(true);

  // Checkout modal state
  const [checkoutPlan, setCheckoutPlan] = useState<Plan | null>(null);
  const [userEmail, setUserEmail] = useState("");
  const [contactType, setContactType] = useState("wechat");
  const [contact, setContact] = useState("");
  const [remark, setRemark] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Pending dialog state
  const [showPendingDialog, setShowPendingDialog] = useState(false);
  const [submittedPlanName, setSubmittedPlanName] = useState("");

  useEffect(() => {
    let ignore = false;

    Promise.all([
      getPlanMarketPlans().catch(() => null),
      getCurrentSubscription().catch(() => null),
      getProfile().catch(() => null),
    ]).then(([plansRes, subRes, profileRes]) => {
      if (ignore) return;
      if (plansRes) setPlans(plansRes.items);
      if (subRes) setCurrentSub(subRes);
      if (profileRes?.email) setUserEmail(profileRes.email);
      setLoading(false);
    });

    return () => {
      ignore = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const personalPlans = plans
    .filter((p) => classifyPlan(p) === "personal")
    .sort((a, b) => a.sortOrder - b.sortOrder);

  const businessPlans = plans
    .filter((p) => classifyPlan(p) === "business")
    .sort((a, b) => a.sortOrder - b.sortOrder);

  function handleOpenCheckout(plan: Plan) {
    const price = getDisplayPrice(plan);
    if (price?.billingPeriod === "sales") {
      toast.info(t("userPages.subscribe.salesUpgradeNotice"));
      return;
    }
    setContact("");
    setRemark("");
    setContactType("wechat");
    setCheckoutPlan(plan);
  }

  function handleCloseCheckout() {
    setCheckoutPlan(null);
  }

  async function handleCheckoutSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!checkoutPlan) return;

    setIsSubmitting(true);
    try {
      await upgradeSubscription(checkoutPlan.id);
      setSubmittedPlanName(checkoutPlan.name);
      setCheckoutPlan(null);
      setShowPendingDialog(true);
    } catch (err: unknown) {
      const apiErr = err as ApiError;
      toast.error(apiErr?.message || t("userPages.subscribe.upgradeFailed"));
    } finally {
      setIsSubmitting(false);
    }
  }

  function renderPlanCard(plan: Plan) {
    const isCurrentPlan = currentSub?.subscription.planId === plan.id;
    const price = getDisplayPrice(plan);
    const isSalesOnly = price?.billingPeriod === "sales";
    const isLowerLevel = !isCurrentPlan && currentSub != null && plan.level < currentSub.plan.level;
    const isDisabled = isCurrentPlan || isLowerLevel || !price;

    function getButtonLabel() {
      if (isCurrentPlan) return t("userPages.subscribe.currentPlan");
      if (isSalesOnly) return t("userPages.subscribe.contactSales");
      if (isLowerLevel) return t("userPages.subscribe.higherPlan");
      if (!price) return t("userPages.subscribe.priceNotConfigured");
      return plan.isRecommended ? t("userPages.subscribe.upgradeNow") : t("userPages.subscribe.choosePlan");
    }

    const localized = plan.localizedContent?.[locale === "zh-CN" ? "zh" : "en"];
    const detailsAvailable = Boolean(localized?.description || localized?.subtitle || localized?.highlightItems?.length);
    const features = localized?.highlightItems ?? [];

    return (
      <article
        key={plan.id}
        className={`relative rounded-[14px] bg-white p-6 ${
          plan.isRecommended
            ? "border-2 border-[#23262d]"
            : "border border-[#deded9]"
        }`}
      >
        {plan.isRecommended && !isCurrentPlan && (
          <span className="absolute right-4 top-4 rounded-full bg-[#111] px-2.5 py-1 text-[11px] text-white">
            {t("userPages.subscribe.popular")}
          </span>
        )}
        {isCurrentPlan && (
          <span className="absolute right-4 top-4 rounded-full bg-[#eef8e8] px-2.5 py-1 text-[11px] text-[#4f8a2e]">
            {t("userPages.subscribe.currentPlan")}
          </span>
        )}

        <div className="mb-5">
          <h2 className="text-[22px] font-bold text-[#1f232b]">{plan.name}</h2>
          {localized?.subtitle && (
            <p className="mt-0.5 text-[13px] text-[#7a808b]">{localized.subtitle}</p>
          )}
        </div>

        <p className="mb-4 text-[30px] font-bold">
          <PriceDisplay price={price} t={t} locale={locale} />
        </p>

        {detailsAvailable ? (
          <p className="mb-4 text-[13px] text-[#656b76]">{localized?.description}</p>
        ) : (
          <p className="mb-4 text-[13px] text-[#656b76]">{t("userPages.subscribe.detailsUnavailable")}</p>
        )}

        <button
          type="button"
          onClick={() => { if (!isDisabled) handleOpenCheckout(plan); }}
          disabled={isDisabled}
          className={`mb-5 h-11 w-full rounded-[10px] text-[14px] font-semibold ${
            isDisabled
              ? "cursor-default border border-[#d7dbe3] bg-[#f5f6f8] text-[#8a8f99]"
              : plan.isRecommended
                ? "bg-[#111] text-white"
                : "border border-[#d7dbe3] bg-white text-[#252930]"
          }`}
        >
          {getButtonLabel()}
        </button>

        {features.length > 0 && (
          <ul className="space-y-2 text-[14px] text-[#3c4250]">
            {features.map((item, i) => (
              // eslint-disable-next-line react/no-array-index-key
              <li key={i}>{item}</li>
            ))}
          </ul>
        )}
      </article>
    );
  }

  const checkoutPrice = checkoutPlan ? getDisplayPrice(checkoutPlan) : null;
  const checkoutPriceStr = formatCheckoutPrice(checkoutPrice, t, locale);
  const checkoutPeriodStr = getPricePeriodLabel(checkoutPrice, t);

  return (
    <>
      <section className="relative mx-auto min-h-screen w-full max-w-[1152px] px-4 pb-10 pt-[82px] text-[#2a2d33] sm:px-6 lg:px-10">
        <button
          type="button"
          onClick={() => router.back()}
          aria-label={t("userPages.common.close")}
          className="absolute right-10 top-10 grid h-8 w-8 place-items-center rounded-[8px] text-[#111318] hover:bg-[#f4f5f7]"
        >
          <svg viewBox="0 0 24 24" className="h-[22px] w-[22px]" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>

        <h1 className="mb-[38px] text-center text-[34px] font-extrabold">{t("userPages.subscribe.title")}</h1>

        <div className="mx-auto mb-[30px] flex w-max gap-3 rounded-xl bg-[#f5f6f8] p-1.5">
          <button
            type="button"
            onClick={() => setTab("personal")}
            className={`h-[45px] rounded-[10px] px-[22px] text-[16px] ${
              tab === "personal" ? "bg-white text-[#252930] shadow-[0_2px_9px_rgba(20,28,42,0.12)]" : "text-[#8a8f99]"
            }`}
          >
            {t("userPages.subscribe.personal")}
          </button>
          <button
            type="button"
            onClick={() => setTab("business")}
            className={`h-[45px] rounded-[10px] px-[22px] text-[16px] ${
              tab === "business" ? "bg-white text-[#252930] shadow-[0_2px_9px_rgba(20,28,42,0.12)]" : "text-[#8a8f99]"
            }`}
          >
            Business
          </button>
        </div>

        {loading ? (
          <div className="flex min-h-[300px] items-center justify-center">
            <p className="text-[15px] text-[#8a8f99]">{t("userPages.subscribe.loading")}</p>
          </div>
        ) : tab === "personal" ? (
          personalPlans.length > 0 ? (
            <div
              className={`mx-auto grid max-w-[1072px] gap-[22px] ${
                personalPlans.length >= 3
                  ? "md:grid-cols-3"
                  : personalPlans.length === 2
                    ? "md:grid-cols-2"
                    : ""
              }`}
            >
              {personalPlans.map(renderPlanCard)}
            </div>
          ) : (
            // fallback: 暂无 API 数据时保留原有硬编码个人版套餐
            <div className="mx-auto grid max-w-[1072px] gap-[22px] md:grid-cols-3">
              <article className="rounded-[14px] border border-[#deded9] bg-white p-6">
                <div className="mb-5 flex items-center gap-3">
                  <span className="grid h-9 w-9 place-items-center rounded-xl bg-[#f2f4f8] text-[18px]">⌁</span>
                  <div>
                    <h2 className="text-[22px] font-bold text-[#1f232b]">{t("userPages.subscribe.free")}</h2>
                    <p className="text-[13px] text-[#7a808b]">{t("userPages.subscribe.freeSubtitle")}</p>
                  </div>
                </div>
                <p className="mb-4 text-[30px] font-bold">¥0</p>
                <button type="button" onClick={() => toast.info("功能开发中")} className="mb-5 h-11 w-full rounded-[10px] border border-[#d7dbe3] bg-white text-[14px] font-semibold text-[#252930]">
                  {t("userPages.subscribe.freeUse")}
                </button>
                <ul className="space-y-2 text-[14px] text-[#3c4250]">
                  {tList("userPages.subscribe.freeFeatures").map((item) => <li key={item}>{item}</li>)}
                </ul>
              </article>

              <article className="relative rounded-[14px] border-2 border-[#23262d] bg-white p-6">
                <span className="absolute right-4 top-4 rounded-full bg-[#111] px-2.5 py-1 text-[11px] text-white">{t("userPages.subscribe.popular")}</span>
                <div className="mb-5 flex items-center gap-3">
                  <span className="grid h-9 w-9 place-items-center rounded-xl bg-[#fff4e2] text-[18px]">⚡</span>
                  <div>
                    <h2 className="text-[22px] font-bold text-[#1f232b]">{t("userPages.subscribe.pro")}</h2>
                    <p className="text-[13px] text-[#7a808b]">{t("userPages.subscribe.proSubtitle")}</p>
                  </div>
                </div>
                <p className="mb-4 text-[30px] font-bold">¥106 <span className="text-[13px] font-normal text-[#6f7683]">{t("userPages.subscribe.monthly")}</span></p>
                <button type="button" onClick={() => toast.info("功能开发中")} className="mb-5 h-11 w-full rounded-[10px] bg-[#111] text-[14px] font-semibold text-white">
                  {t("userPages.subscribe.getPro")}
                </button>
                <ul className="space-y-2 text-[14px] text-[#3c4250]">
                  {tList("userPages.subscribe.proFeatures").map((item) => <li key={item}>{item}</li>)}
                </ul>
              </article>

              <article className="rounded-[14px] border border-[#deded9] bg-white p-6">
                <div className="mb-5 flex items-center gap-3">
                  <span className="grid h-9 w-9 place-items-center rounded-xl bg-[#eef2f8] text-[18px]">🚀</span>
                  <div>
                    <h2 className="text-[22px] font-bold text-[#1f232b]">{t("userPages.subscribe.max")}</h2>
                    <p className="text-[13px] text-[#7a808b]">{t("userPages.subscribe.maxSubtitle")}</p>
                  </div>
                </div>
                <p className="mb-4 text-[30px] font-bold">¥625{t("userPages.subscribe.from")} <span className="text-[13px] font-normal text-[#6f7683]">{t("userPages.subscribe.monthly")}</span></p>
                <button type="button" onClick={() => toast.info("功能开发中")} className="mb-2 h-11 w-full rounded-[10px] bg-[#111] text-[14px] font-semibold text-white">
                  {t("userPages.subscribe.getMax")}
                </button>
                <p className="mb-5 text-[12px] text-[#7a808b]">{t("userPages.subscribe.noCommitment")}</p>
                <ul className="space-y-2 text-[14px] text-[#3c4250]">
                  {tList("userPages.subscribe.maxFeatures").map((item) => <li key={item}>{item}</li>)}
                </ul>
              </article>
            </div>
          )
        ) : (
          businessPlans.length > 0 ? (
            <div
              className={`mx-auto grid max-w-[730px] gap-[22px] ${
                businessPlans.length >= 2 ? "md:grid-cols-2" : ""
              }`}
            >
              {businessPlans.map(renderPlanCard)}
            </div>
          ) : (
            // fallback: 暂无 API 数据时保留原有硬编码 Business 套餐
            <div className="mx-auto grid max-w-[730px] gap-[22px] md:grid-cols-2">
              <article className="min-h-[496px] rounded-[14px] border border-[#deded9] bg-white p-8">
                <h2 className="mb-4 text-[22px] font-bold text-[#1f232b]">{t("userPages.subscribe.free")}</h2>
                <p className="mb-4 text-[32px] font-bold">$0 <span className="text-[13px] font-normal text-[#6f7683]">{t("userPages.subscribe.usdMonthly")}</span></p>
                <p className="mb-4 text-[14px] text-[#656b76]">{t("userPages.subscribe.learnAi")}</p>
                <button type="button" disabled className="mb-5 h-11 w-full rounded-[10px] border border-[#dfe3eb] bg-[#f5f6f8] text-[14px] text-[#8a8f99]">
                  {t("userPages.subscribe.currentPlan")}
                </button>
                <ul className="space-y-2 text-[14px] text-[#3c4250]">
                  {tList("userPages.subscribe.businessFreeFeatures").map((item) => <li key={item}>{item}</li>)}
                </ul>
              </article>

              <article className="min-h-[496px] rounded-[14px] border-2 border-[#242424] bg-white p-8">
                <h2 className="mb-4 text-[22px] font-bold text-[#1f232b]">Business</h2>
                <p className="mb-4 text-[32px] font-bold">$20 <span className="text-[13px] font-normal text-[#6f7683]">{t("userPages.subscribe.usdMonthly")}</span></p>
                <p className="mb-4 text-[14px] text-[#656b76]">{t("userPages.subscribe.businessSubtitle")}</p>
                <button type="button" onClick={() => toast.info("功能开发中")} className="mb-5 h-11 w-full rounded-[10px] bg-[#111] text-[14px] font-semibold text-white">
                  {t("userPages.subscribe.upgrade")}
                </button>
                <ul className="space-y-2 text-[14px] text-[#3c4250]">
                  {tList("userPages.subscribe.businessFeatures").map((item) => <li key={item}>{item}</li>)}
                </ul>
              </article>
            </div>
          )
        )}
      </section>

      {/* Checkout modal */}
      {checkoutPlan && (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-auto bg-[#fcfcfc] px-4 py-3">
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="checkoutTitle"
            className="relative my-auto w-full max-w-[420px] rounded-[16px] border border-[#e5e5e5] bg-white p-6 text-[#111]"
          >
            <button
              type="button"
              onClick={handleCloseCheckout}
              aria-label={t("userPages.subscribe.checkoutBack")}
              className="absolute left-[22px] top-6 grid h-6 w-6 place-items-center text-[#111]"
            >
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M19 12H5m6 6-6-6 6-6" />
              </svg>
            </button>

            <h2 id="checkoutTitle" className="mb-[22px] ml-[30px] text-[18px] font-semibold leading-[26px]">{t("userPages.subscribe.checkoutTitle")}</h2>

            {/* Order summary */}
            <section>
              <h3 className="mb-[14px] text-[14px] font-semibold">{checkoutPlan.name}</h3>
              <div className="grid gap-3 border-b border-[#e5e5e5] pb-5">
                <div className="flex justify-between gap-3 text-[14px] text-[#737373]">
                  <span>{t("userPages.subscribe.planPrice")}{checkoutPeriodStr}</span>
                  <strong className="font-[650] text-[#111]">{checkoutPriceStr}</strong>
                </div>
                <div className="flex justify-between gap-3 text-[14px] text-[#737373]">
                  <span>{t("userPages.subscribe.estimatedTax")}</span>
                  <strong className="font-[650] text-[#111]">{locale === "zh-CN" ? "¥0.00" : "US$0.00"}</strong>
                </div>
                <div className="flex justify-between gap-3 border-t border-[#e5e5e5] pt-3 text-[14px] text-[#111]">
                  <span>{t("userPages.subscribe.offlinePayable")}</span>
                  <strong className="font-[650]">{checkoutPriceStr}</strong>
                </div>
              </div>
            </section>

            {/* Application form */}
            <form onSubmit={handleCheckoutSubmit} className="mt-6">
              <h3 className="mb-[14px] text-[14px] font-semibold">{t("userPages.subscribe.applicationInfo")}</h3>

              <div>
                <label className="mb-1.5 block text-[12px] leading-[18px] text-[#8c8c8c]">{t("userPages.subscribe.registeredEmail")}</label>
                <div className="flex min-h-9 items-center gap-2 rounded-[8px] bg-[#fafafa] px-3">
                  <svg viewBox="0 0 24 24" className="h-[15px] w-[15px] shrink-0 text-[#8c8c8c]" fill="none" stroke="currentColor" strokeWidth="1.6">
                    <rect x="3" y="5" width="18" height="14" rx="2" />
                    <path d="m3 6 9 7 9-7" />
                  </svg>
                  <input
                    type="email"
                    value={userEmail}
                    readOnly
                    className="min-w-0 flex-1 border-0 bg-transparent p-0 text-[14px] text-[#111] outline-none"
                    style={{ textOverflow: "ellipsis" }}
                    autoComplete="email"
                  />
                  <span className="shrink-0 rounded-full bg-[#eaf1f8] px-2.5 py-[3px] text-[11px] whitespace-nowrap text-[#3974b6]">{t("userPages.subscribe.autoFilled")}</span>
                </div>
              </div>

              <div className="mt-4">
                <label className="mb-1.5 block text-[12px] leading-[18px] text-[#8c8c8c]">{t("userPages.subscribe.contactInfo")}</label>
                <div className="grid gap-2" style={{ gridTemplateColumns: "110px 1fr" }}>
                  <select
                    value={contactType}
                    onChange={(e) => setContactType(e.target.value)}
                    className="h-9 cursor-pointer rounded-[6px] border border-[#e0e0e0] bg-white px-2.5 text-[14px] text-[#171717] outline-none focus-visible:outline-[2px] focus-visible:outline-[#9bc1ff] focus-visible:outline-offset-2"
                  >
                    <option value="wechat">{locale === "zh-CN" ? "微信" : "WeChat"}</option>
                    <option value="phone">{locale === "zh-CN" ? "手机号" : "Phone"}</option>
                    <option value="telegram">Telegram</option>
                  </select>
                  <input
                    type="text"
                    value={contact}
                    onChange={(e) => setContact(e.target.value)}
                    placeholder={t("userPages.subscribe.contactPlaceholder")}
                    maxLength={100}
                    className="h-9 rounded-[6px] border border-[#e0e0e0] bg-white px-3 text-[14px] text-[#171717] outline-none placeholder:text-[#858585] focus-visible:outline-[2px] focus-visible:outline-[#9bc1ff] focus-visible:outline-offset-2"
                  />
                </div>
              </div>

              <div className="mt-4">
                <label className="mb-1.5 block text-[12px] leading-[18px] text-[#8c8c8c]">{t("userPages.subscribe.remark")}</label>
                <textarea
                  value={remark}
                  onChange={(e) => setRemark(e.target.value)}
                  placeholder={t("userPages.subscribe.remarkPlaceholder")}
                  maxLength={1000}
                  rows={3}
                  className="block min-h-[80px] w-full resize-y rounded-[6px] border border-[#e0e0e0] bg-white px-3 py-2 text-[14px] leading-[22px] text-[#171717] outline-none placeholder:text-[#858585] focus-visible:outline-[2px] focus-visible:outline-[#9bc1ff] focus-visible:outline-offset-2"
                />
              </div>

              <button
                type="submit"
                disabled={isSubmitting}
                className="mt-[22px] h-11 w-full rounded-[8px] bg-[#0a0a0a] text-[14px] font-semibold text-white transition-colors hover:bg-[#252525] disabled:opacity-60"
              >
                {isSubmitting ? t("userPages.subscribe.submitting") : t("userPages.subscribe.submitApplication")}
              </button>
              <p className="mt-3 text-[12px] leading-[20px] text-[#8c8c8c]">
                {t("userPages.subscribe.checkoutNotice")}
              </p>
            </form>
          </section>
        </div>
      )}

      {/* Pending/submitted dialog */}
      {showPendingDialog && (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-[rgba(20,20,20,0.38)] px-4 backdrop-blur-[2px]"
          onClick={(e) => { if (e.target === e.currentTarget) setShowPendingDialog(false); }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="pendingDialogTitle"
            className="relative w-full max-w-[460px] overflow-auto rounded-[18px] bg-white px-[30px] pb-7 pt-[38px] text-center text-[#25221f]"
            style={{ boxShadow: "0 22px 64px rgba(31,27,29,0.22)" }}
          >
            <button
              type="button"
              onClick={() => setShowPendingDialog(false)}
              aria-label={t("userPages.common.close")}
              className="absolute right-4 top-4 grid h-8 w-8 place-items-center rounded-[8px] text-[#111318] hover:bg-[#f4f5f7]"
            >
              <svg viewBox="0 0 24 24" className="h-[22px] w-[22px]" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>

            <span className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-[#fff2df] text-[#c77700]">
              <svg viewBox="0 0 24 24" className="h-[30px] w-[30px]" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="8" />
                <path d="M12 8v5l3 2" />
              </svg>
            </span>

            <h2 id="pendingDialogTitle" className="mb-2 mt-[18px] text-[24px] font-bold text-[#1f2937]">{t("userPages.subscribe.submittedTitle")}</h2>
            <p className="text-[14px] leading-[1.7] text-[#6f6a64]">
              {t("userPages.subscribe.submittedBody", { plan: submittedPlanName })}
            </p>

            <div className="my-[22px] grid grid-cols-[1fr_auto] gap-x-3.5 gap-y-1.5 rounded-[12px] border border-[#eee4d5] bg-[#fffaf2] px-[15px] py-[15px] text-left">
              <span className="text-[13px] text-[#756d64]">{t("userPages.subscribe.currentStatus")}</span>
              <span className="rounded-full bg-[#fff0d7] px-2 py-[3px] text-[12px] text-[#a45f00]">{t("userPages.subscribe.pendingReview")}</span>
              <span className="col-span-2 text-[11px] leading-[1.5] text-[#999187]">{t("userPages.subscribe.pendingNotice")}</span>
            </div>

            <button
              type="button"
              onClick={() => setShowPendingDialog(false)}
              className="w-full rounded-[12px] bg-[#232f3e] px-[18px] py-[13px] text-[15px] font-medium text-white"
            >
              {t("userPages.subscribe.backToPlans")}
            </button>
          </section>
        </div>
      )}
    </>
  );
}
