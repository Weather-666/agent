from typing import Literal

from pydantic import BaseModel, Field, field_validator


CreditEntryType = Literal[
    "monthly_grant",
    "upgrade_grant",
    "turn_charge",
    "manual_adjustment",
]
# `shadow` remains readable for immutable records created before enforced settlement became
# unconditional. New settlements always use `enforced` and never produce the legacy status.
CreditUsageStatus = Literal["settled", "shadow", "unmetered", "not_chargeable"]
CreditSettlementMode = Literal["shadow", "enforced"]


class CreditPeriod(BaseModel):
    id: str
    tenantId: str
    periodStart: str
    highestPlanCreditLimit: int = Field(ge=0)
    createdAt: str
    updatedAt: str


class CreditSummary(BaseModel):
    tenantId: str
    planId: str
    planCode: str
    planName: str
    periodStart: str
    periodEnd: str
    monthlyCreditLimit: int = Field(ge=0)
    grantedCredits: int = Field(ge=0)
    adjustmentCredits: int
    estimatedUsedCredits: int = Field(ge=0)
    deductedCredits: int = Field(ge=0)
    remainingCredits: int = Field(ge=0)
    enforcementEnabled: bool


class AdminCreditSummary(CreditSummary):
    ledgerBalance: int
    overdrawnCredits: int = Field(ge=0)


class CreditLedgerEntry(BaseModel):
    id: str
    periodId: str
    tenantId: str
    beneficiaryUserId: str | None = None
    entryType: CreditEntryType
    amount: int
    referenceId: str | None = None
    idempotencyKey: str | None = None
    actorUserId: str | None = None
    reason: str | None = None
    createdAt: str


class CreditLedgerListResponse(BaseModel):
    items: list[CreditLedgerEntry]
    total: int
    page: int
    pageSize: int


class CreditAdjustmentRequest(BaseModel):
    amount: int
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("amount")
    @classmethod
    def amount_must_be_non_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("amount must be non-zero")
        return value

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reason must not be blank")
        return normalized


class CreditUsageRecord(BaseModel):
    id: str
    turnId: str
    periodId: str
    tenantId: str
    userId: str
    sessionId: str
    tokenUsed: int = Field(ge=0)
    usageSource: str
    calculatorVersion: str
    tokensPerCredit: int
    roundingMode: str
    tokenUsageScope: str | None = None
    acpSessionId: str | None = None
    calculationScale: int | None = Field(default=None, gt=0)
    cachedInputWeightScaled: int | None = Field(default=None, ge=0)
    previousUsageSize: int | None = Field(default=None, ge=0)
    currentUsageSize: int | None = Field(default=None, ge=0)
    cachedTokens: int | None = Field(default=None, ge=0)
    uncachedTokens: int | None = Field(default=None, ge=0)
    effectiveTokensScaled: int | None = Field(default=None, ge=0)
    calculatedCredits: int = Field(ge=0)
    deductedCredits: int = Field(ge=0)
    settlementMode: CreditSettlementMode
    status: CreditUsageStatus
    nonChargeReason: str | None = None
    createdAt: str
