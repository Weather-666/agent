import { type Translate } from "@/lib/i18n";
import { type BillingPeriod, type Plan, type PlanStatus } from "@/lib/api/admin-client";

export type PlanForm = {
  id: string;
  name: string;
  type: string;
  level: string;
  description: string;
  subtitle: string;
  badgeLabel: string;
  highlightItems: string;
  zhSubtitle: string;
  zhDescription: string;
  zhBadgeLabel: string;
  zhHighlightItems: string;
  enSubtitle: string;
  enDescription: string;
  enBadgeLabel: string;
  enHighlightItems: string;
  status: PlanStatus;
  isRecommended: boolean;
  sortOrder: string;
  monthlyPrice: string;
  yearlyPrice: string;
  currency: "CNY" | "USD";
  freePrice: boolean;
  salesPrice: boolean;
  monthlyCreditLimit: string;
  allExperts: boolean;
  seatLimit: string;
  singleTurnTokenLimit: string;
  modelTiers: string;
  featureTeamManagement: boolean;
  featureApiAccess: boolean;
  featurePrivateDeployment: boolean;
  expertIds: string[];
};

export const defaultForm: PlanForm = {
  id: "",
  name: "",
  type: "",
  level: "1",
  description: "",
  subtitle: "",
  badgeLabel: "",
  highlightItems: "",
  zhSubtitle: "",
  zhDescription: "",
  zhBadgeLabel: "",
  zhHighlightItems: "",
  enSubtitle: "",
  enDescription: "",
  enBadgeLabel: "",
  enHighlightItems: "",
  status: "disabled",
  isRecommended: false,
  sortOrder: "0",
  monthlyPrice: "",
  yearlyPrice: "",
  currency: "CNY",
  freePrice: false,
  salesPrice: false,
  monthlyCreditLimit: "0",
  allExperts: false,
  seatLimit: "1",
  singleTurnTokenLimit: "",
  modelTiers: "core",
  featureTeamManagement: false,
  featureApiAccess: false,
  featurePrivateDeployment: false,
  expertIds: [],
};

export const PLAN_LEVEL_MIN = 1;
export const PLAN_LEVEL_MAX = 99;
export const PLAN_SORT_ORDER_MIN = 0;
export const PLAN_SORT_ORDER_MAX = 9999;

export function getErrorMessage(error: unknown, fallback: string) {
  if (error && typeof error === "object" && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }

  return fallback;
}

export function formatDate(value?: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return `${date.getFullYear()}/${String(date.getMonth() + 1).padStart(2, "0")}/${String(date.getDate()).padStart(2, "0")}`;
}

export function formatInteger(value?: number | null) {
  if (typeof value !== "number") return "-";
  return value.toLocaleString("zh-CN");
}

export function formatTokenLimit(value: number | null | undefined, t: Translate) {
  if (typeof value !== "number") return "-";
  if (value >= 10000) return t("adminPlans.tokenTenThousand", { value: Math.round(value / 10000).toLocaleString("zh-CN") });
  return value.toLocaleString("zh-CN");
}

export function currencyToCents(value: string) {
  const normalized = value.trim().replace(/[¥$,\s]/g, "");
  if (!normalized) return null;
  const amount = Number(normalized);
  if (!Number.isFinite(amount) || amount < 0) return null;
  return Math.round(amount * 100);
}

export function centsToYuan(value?: number) {
  if (typeof value !== "number") return "";
  return String(value / 100);
}

export function findPrice(plan: Plan, period: BillingPeriod) {
  return plan.prices.find((price) => price.billingPeriod === period && price.isEnabled);
}

export function formatPrice(plan: Plan, period: BillingPeriod, t: Translate) {
  const price = findPrice(plan, period) ?? (period === "monthly" ? findPrice(plan, "free") : undefined);
  if (!price) return t("adminPlans.priceNotConfigured");
  if (price.billingPeriod === "free" || price.amountCents === 0) return t("adminPlans.priceFree");
  if (price.billingPeriod === "sales") return t("adminPlans.priceCustom");
  const amount = formatCurrency(price.currency, price.amountCents / 100, "zh-CN");
  return period === "yearly"
    ? t("adminPlans.pricePerYear", { amount })
    : t("adminPlans.pricePerMonth", { amount });
}

export function formatCurrency(currency: string, amount: number, locale: string) {
  try {
    const number = new Intl.NumberFormat(locale, {
      maximumFractionDigits: 2,
    }).format(amount);
    return currency === "USD" ? `US$${number}` : `¥${number}`;
  } catch {
    return `${currency} ${amount}`;
  }
}

export function getPrimaryBillingPeriod(plan: Plan) {
  const enabledPrices = plan.prices.filter((price) => price.isEnabled);
  return (
    enabledPrices.find((price) => price.billingPeriod === "free")?.billingPeriod ||
    enabledPrices.find((price) => price.billingPeriod === "monthly")?.billingPeriod ||
    enabledPrices.find((price) => price.billingPeriod === "yearly")?.billingPeriod ||
    enabledPrices.find((price) => price.billingPeriod === "sales")?.billingPeriod ||
    plan.prices[0]?.billingPeriod ||
    "free"
  );
}

export function billingPeriodLabel(period: BillingPeriod, t: Translate) {
  if (period === "free") return t("adminPlans.priceFree");
  if (period === "monthly") return t("adminPlans.billingMonthly");
  if (period === "yearly") return t("adminPlans.billingYearly");
  if (period === "sales") return t("adminPlans.billingSales");
  return period;
}

export function getTenantSubscriptionTypeFilter(plan: Plan, t: Translate) {
  return `${plan.name} · ${billingPeriodLabel(getPrimaryBillingPeriod(plan), t)}`;
}

export function getPlanType(plan: Plan, t: Translate) {
  return plan.typeLabel || t("adminPlans.planTypeNotSet");
}

export function getSubscriberCount(plan: Plan) {
  const candidates = [
    plan.subscriberCount,
    plan.subscriptionCount,
    plan.subscribedUserCount,
    plan.subscribedTenantCount,
    plan.subscriberTenantCount,
    plan.activeSubscriptionCount,
    plan.tenantCount,
  ];

  const value = candidates.find((item) => typeof item === "number");
  return typeof value === "number" ? value : null;
}

export function planToForm(plan: Plan): PlanForm {
  const monthly = findPrice(plan, "monthly");
  const yearly = findPrice(plan, "yearly");
  const sales = findPrice(plan, "sales");
  const features = plan.entitlements?.features ?? {};
  const zh = plan.localizedContent?.zh;
  const en = plan.localizedContent?.en;

  return {
    id: plan.id,
    name: plan.name,
    type: plan.typeLabel || "",
    level: String(plan.level),
    description: plan.description,
    subtitle: plan.subtitle || "",
    badgeLabel: plan.badgeLabel || "",
    highlightItems: (plan.highlightItems ?? []).join("; "),
    zhSubtitle: zh?.subtitle ?? plan.subtitle ?? "",
    zhDescription: zh?.description ?? plan.description ?? "",
    zhBadgeLabel: zh?.badgeLabel ?? plan.badgeLabel ?? "",
    zhHighlightItems: (zh?.highlightItems ?? plan.highlightItems ?? []).join("; "),
    enSubtitle: en?.subtitle ?? "",
    enDescription: en?.description ?? "",
    enBadgeLabel: en?.badgeLabel ?? "",
    enHighlightItems: (en?.highlightItems ?? []).join("; "),
    status: plan.status,
    isRecommended: plan.isRecommended,
    sortOrder: String(plan.sortOrder),
    monthlyPrice: centsToYuan(monthly?.amountCents),
    yearlyPrice: centsToYuan(yearly?.amountCents),
    currency: (monthly?.currency ?? yearly?.currency ?? sales?.currency ?? "CNY").toUpperCase() === "USD" ? "USD" : "CNY",
    freePrice: Boolean(findPrice(plan, "free")),
    salesPrice: Boolean(sales),
    monthlyCreditLimit: String(plan.entitlements?.monthlyCreditLimit ?? 0),
    allExperts: Boolean(plan.entitlements?.allExperts),
    seatLimit: String(plan.entitlements?.seatLimit ?? 1),
    singleTurnTokenLimit: plan.entitlements?.singleTurnTokenLimit ? String(plan.entitlements.singleTurnTokenLimit) : "",
    modelTiers: (plan.entitlements?.modelTiers ?? ["core"]).join(", "),
    featureTeamManagement: Boolean(features.teamManagement),
    featureApiAccess: Boolean(features.apiAccess),
    featurePrivateDeployment: Boolean(features.privateDeployment),
    expertIds: plan.expertIds,
  };
}

export function buildPrices(form: PlanForm, t: Translate) {
  const items = [];
  const monthlyCents = currencyToCents(form.monthlyPrice);
  const yearlyCents = currencyToCents(form.yearlyPrice);
  const currency = form.currency;

  if (form.freePrice && !form.salesPrice) {
    items.push({
      billingPeriod: "free" as const,
      currency: "CNY",
      amountCents: 0,
      discountLabel: null,
      isEnabled: true,
    });
  }

  if (monthlyCents !== null) {
    items.push({
      billingPeriod: "monthly" as const,
      currency,
      amountCents: monthlyCents,
      discountLabel: null,
      isEnabled: true,
    });
  }

  if (yearlyCents !== null) {
    items.push({
      billingPeriod: "yearly" as const,
      currency,
      amountCents: yearlyCents,
      discountLabel: t("adminPlans.yearlyDiscount"),
      isEnabled: true,
    });
  }

  if (form.salesPrice) {
    items.push({
      billingPeriod: "sales" as const,
      currency,
      amountCents: 0,
      discountLabel: t("adminPlans.contactSales"),
      isEnabled: true,
    });
  }

  return { items };
}

export function parsePositiveInt(value: string, fallback: number) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

export function isIntegerInRange(value: string, min: number, max: number) {
  if (!/^\d+$/.test(value.trim())) return false;
  const parsed = Number.parseInt(value, 10);
  return parsed >= min && parsed <= max;
}
