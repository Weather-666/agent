from typing import Any, Literal

from pydantic import BaseModel, Field


PlanStatus = Literal["active", "disabled"]
BillingPeriod = Literal["free", "monthly", "yearly", "sales"]
# Raw, persisted subscription state as stored in the `subscriptions` table.
SubscriptionStatus = Literal["active", "trialing", "past_due", "cancelled", "expired"]
# Derived, client-facing status used by admin list filters and display. Computed from the raw
# status plus the period-end date (see app/services/subscription_status.py). This is the ONLY
# vocabulary the `subscriptionStatus` filter accepts and the only value the `status` field returns.
SubscriptionDisplayStatus = Literal["active", "expiring_soon", "expired"]


class PlanPrice(BaseModel):
    id: str
    planId: str
    billingPeriod: BillingPeriod
    currency: str
    amountCents: int
    discountLabel: str | None = None
    isEnabled: bool
    createdAt: str
    updatedAt: str


class LocalizedPlanContent(BaseModel):
    subtitle: str | None = None
    description: str | None = None
    badgeLabel: str | None = None
    highlightItems: list[str] = Field(default_factory=list)


class ReplacePlanPriceRequest(BaseModel):
    billingPeriod: BillingPeriod
    currency: str
    amountCents: int = Field(ge=0)
    discountLabel: str | None = None
    isEnabled: bool = True


class ReplacePlanPricesRequest(BaseModel):
    items: list[ReplacePlanPriceRequest] = Field(default_factory=list)


class PlanEntitlements(BaseModel):
    id: str
    planId: str
    monthlyCreditLimit: int = Field(ge=0)
    allExperts: bool
    seatLimit: int
    personalLibraryQuotaBytes: int = Field(ge=0)
    teamLibraryQuotaBytes: int = Field(ge=0)
    teamLibraryEnabled: bool
    singleTurnTokenLimit: int | None = None
    modelTiers: list[str] = Field(default_factory=list)
    features: dict[str, Any] = Field(default_factory=dict)
    createdAt: str
    updatedAt: str


class ReplacePlanEntitlementsRequest(BaseModel):
    monthlyCreditLimit: int = Field(ge=0)
    allExperts: bool
    seatLimit: int = Field(ge=1)
    # Optional for compatibility with the currently deployed plan editor. Omitted Library fields
    # preserve the existing values instead of silently clearing newly added entitlements.
    personalLibraryQuotaBytes: int | None = Field(default=None, ge=0)
    teamLibraryQuotaBytes: int | None = Field(default=None, ge=0)
    teamLibraryEnabled: bool | None = None
    singleTurnTokenLimit: int | None = Field(default=None, ge=0)
    modelTiers: list[str] = Field(default_factory=list)
    features: dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
    id: str
    code: str
    name: str
    level: int
    description: str
    typeLabel: str | None = None
    subtitle: str | None = None
    badgeLabel: str | None = None
    highlightItems: list[str] = Field(default_factory=list)
    localizedContent: dict[str, LocalizedPlanContent] = Field(default_factory=dict)
    upgradeRules: dict[str, Any] = Field(default_factory=dict)
    status: PlanStatus
    isRecommended: bool
    sortOrder: int
    subscriptionCount: int = 0
    prices: list[PlanPrice] = Field(default_factory=list)
    entitlements: PlanEntitlements | None = None
    expertIds: list[str] = Field(default_factory=list)
    createdAt: str
    updatedAt: str


class CreatePlanRequest(BaseModel):
    code: str | None = None
    name: str
    level: int = Field(ge=1, le=99)
    description: str
    typeLabel: str | None = None
    subtitle: str | None = None
    badgeLabel: str | None = None
    highlightItems: list[str] = Field(default_factory=list)
    localizedContent: dict[str, LocalizedPlanContent] = Field(default_factory=dict)
    upgradeRules: dict[str, Any] = Field(default_factory=dict)
    status: PlanStatus = "active"
    isRecommended: bool = False
    sortOrder: int = Field(default=0, ge=0, le=9999)


class UpdatePlanRequest(BaseModel):
    code: str | None = None
    name: str | None = None
    level: int | None = Field(default=None, ge=1, le=99)
    description: str | None = None
    typeLabel: str | None = None
    subtitle: str | None = None
    badgeLabel: str | None = None
    highlightItems: list[str] | None = None
    localizedContent: dict[str, LocalizedPlanContent] | None = None
    upgradeRules: dict[str, Any] | None = None
    status: PlanStatus | None = None
    isRecommended: bool | None = None
    sortOrder: int | None = Field(default=None, ge=0, le=9999)


class ReplacePlanExpertsRequest(BaseModel):
    expertIds: list[str] = Field(default_factory=list)


class PlanListResponse(BaseModel):
    items: list[Plan]


class TenantSubscription(BaseModel):
    id: str
    tenantId: str
    planId: str
    status: SubscriptionStatus
    billingPeriod: BillingPeriod
    currentPeriodStart: str
    currentPeriodEnd: str | None = None
    cancelAtPeriodEnd: bool
    createdAt: str
    updatedAt: str


class CurrentSubscriptionResponse(BaseModel):
    subscription: TenantSubscription
    plan: Plan


class UpgradeSubscriptionRequest(BaseModel):
    planId: str = Field(min_length=1)
