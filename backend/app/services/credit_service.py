from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.core.config import Settings
from app.core.errors import ApiError
from app.db import DatabaseConnection
from app.domain.audit import AuditCategory, AuditOperationType, AuditResource, AuditTenant
from app.domain.auth import Principal
from app.domain.credits import (
    AdminCreditSummary,
    CreditLedgerEntry,
    CreditPeriod,
    CreditSummary,
    CreditUsageRecord,
)
from app.domain.plans import Plan
from app.services._sql import is_unique_violation
from app.services.audit_service import AuditService
from app.services.credit_repository import CreditRepository, map_ledger_entry
from app.services.plan_repository import PlanRepository
from app.services.subscription_service import SubscriptionService


CALCULATION_SCALE = 10_000
CALCULATOR_VERSION = "estimated-cache-v2"
ROUNDING_MODE = "ceil"
USAGE_SOURCE = "acp_context_snapshot_split"


@dataclass(frozen=True)
class CreditCalculation:
    previous_size: int
    current_size: int
    cached_tokens: int
    uncached_tokens: int
    cached_input_weight_scaled: int
    effective_tokens_scaled: int
    calculated_credits: int


class CreditService:
    def __init__(self, connection: DatabaseConnection, settings: Settings) -> None:
        self.connection = connection
        self.settings = settings
        self.repo = CreditRepository(connection)
        self.plan_repo = PlanRepository(connection)
        self.subscription_service = SubscriptionService(connection)

    def get_current_summary(
        self,
        tenant_id: str,
        *,
        admin: bool = False,
        user_id: str | None = None,
        now: datetime | None = None,
    ) -> CreditSummary | AdminCreditSummary:
        user_scoped = self._uses_user_credit_accounts(tenant_id)
        if user_scoped and user_id is None:
            period, plan = self._default_tenant_period_and_plan(now=now)
            member_user_ids = self.repo.active_member_user_ids(tenant_id)
            member_sums = [
                self.repo.summary_sums(period.id, beneficiary_user_id=member_user_id)
                for member_user_id in member_user_ids
            ]
            sums = {
                key: sum(item[key] for item in member_sums)
                for key in (
                    "granted_credits",
                    "adjustment_credits",
                    "deducted_credits",
                    "ledger_balance",
                    "estimated_used_credits",
                )
            }
        else:
            period, plan = self._period_and_plan(tenant_id, user_id=user_id, now=now)
            beneficiary_user_id = user_id if user_scoped else None
            sums = self.repo.summary_sums(
                period.id,
                beneficiary_user_id=beneficiary_user_id,
            )
        monthly_credit_limit = sums["granted_credits"]
        self.connection.commit()
        period_start = _month_start(now)
        period_end = _next_month(period_start)
        common = {
            "tenantId": tenant_id,
            "planId": plan.id,
            "planCode": plan.code,
            "planName": plan.name,
            "periodStart": period_start.isoformat(),
            "periodEnd": period_end.isoformat(),
            "monthlyCreditLimit": monthly_credit_limit,
            "grantedCredits": sums["granted_credits"],
            "adjustmentCredits": sums["adjustment_credits"],
            "estimatedUsedCredits": sums["estimated_used_credits"],
            "deductedCredits": sums["deducted_credits"],
            "remainingCredits": max(sums["ledger_balance"], 0),
            "enforcementEnabled": True,
        }
        if not admin:
            return CreditSummary(**common)
        return AdminCreditSummary(
            **common,
            ledgerBalance=sums["ledger_balance"],
            overdrawnCredits=max(-sums["ledger_balance"], 0),
        )

    def ensure_turn_allowed(self, tenant_id: str, *, user_id: str | None = None) -> None:
        period, _ = self._period_and_plan(tenant_id, user_id=user_id)
        beneficiary_user_id = user_id if self._uses_user_credit_accounts(tenant_id) else None
        balance = self.repo.ledger_balance(
            period.id, beneficiary_user_id=beneficiary_user_id
        )
        self.connection.commit()
        if balance <= 0:
            message = (
                "User credit balance is exhausted"
                if beneficiary_user_id is not None
                else "Tenant credit balance is exhausted"
            )
            raise ApiError(402, "CREDIT_EXHAUSTED", message)

    def apply_current_plan_limit(
        self,
        tenant_id: str,
        *,
        user_id: str | None = None,
        now: datetime | None = None,
    ) -> CreditPeriod:
        if self._uses_user_credit_accounts(tenant_id) and user_id is None:
            period, _ = self._default_tenant_period_and_plan(now=now)
        else:
            period, _ = self._period_and_plan(tenant_id, user_id=user_id, now=now)
        return period

    def settle_turn(self, turn_id: str) -> CreditUsageRecord:
        existing = self.repo.get_usage_record(turn_id)
        if existing is not None:
            return existing

        turn = self.repo.get_turn_for_settlement(turn_id)
        if turn is None:
            raise ApiError(404, "CHAT_TURN_NOT_FOUND", "Chat Turn not found")
        if str(turn["status"]) == "running":
            raise ApiError(409, "CHAT_TURN_NOT_TERMINAL", "Chat Turn is not terminal")

        tenant_id = str(turn["tenant_id"])
        user_id = str(turn["user_id"])
        period, _ = self._period_and_plan(tenant_id, user_id=user_id)
        beneficiary_user_id = user_id if self._uses_user_credit_accounts(tenant_id) else None
        token_used = max(int(turn.get("token_used") or 0), 0)
        current_size = max(int(turn.get("token_usage_snapshot") or 0), 0)
        previous_size = max(int(turn.get("token_usage_previous_snapshot") or 0), 0)
        if current_size <= 0 and token_used > 0:
            # Compatibility for terminal chat_turns written before absolute snapshots existed.
            current_size = token_used
            previous_size = 0
        calculation = calculate_credit_usage(
            current_size,
            previous_size,
            tokens_per_credit=self.settings.credit_tokens_per_credit,
            cached_input_weight=self.settings.credit_cached_input_weight,
        )
        settlement_mode = "enforced"
        calculated_credits = 0
        deducted_credits = 0
        non_charge_reason: str | None = None

        if bool(turn["is_internal"]):
            status = "not_chargeable"
            non_charge_reason = "internal_turn"
        elif str(turn["status"]) == "failed":
            status = "not_chargeable"
            non_charge_reason = "turn_failed"
        elif str(turn["status"]) == "cancelled":
            status = "not_chargeable"
            non_charge_reason = "turn_cancelled"
        elif current_size <= 0:
            status = "unmetered"
            non_charge_reason = "usage_missing_or_zero"
        else:
            calculated_credits = calculation.calculated_credits
            balance = self.repo.ledger_balance(
                period.id, beneficiary_user_id=beneficiary_user_id
            )
            deducted_credits = min(calculated_credits, max(balance, 0))
            status = "settled"

        now = _now_iso()
        try:
            if deducted_credits > 0:
                self.repo.insert_ledger_entry(
                    entry_id=f"credit_entry_{uuid4().hex}",
                    period_id=period.id,
                    tenant_id=tenant_id,
                    beneficiary_user_id=beneficiary_user_id,
                    entry_type="turn_charge",
                    amount=-deducted_credits,
                    reference_id=turn_id,
                    idempotency_key=None,
                    request_fingerprint=None,
                    actor_user_id=None,
                    reason=None,
                    created_at=now,
                )
            record_id = f"credit_usage_{uuid4().hex}"
            self.repo.insert_usage_record(
                record_id=record_id,
                turn_id=turn_id,
                period_id=period.id,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=str(turn["session_id"]),
                token_used=token_used,
                usage_source=USAGE_SOURCE,
                calculator_version=CALCULATOR_VERSION,
                tokens_per_credit=self.settings.credit_tokens_per_credit,
                rounding_mode=ROUNDING_MODE,
                token_usage_scope=str(turn.get("token_usage_scope") or ""),
                acp_session_id=(
                    str(turn["token_usage_session_id"])
                    if turn.get("token_usage_session_id")
                    else None
                ),
                calculation_scale=CALCULATION_SCALE,
                cached_input_weight_scaled=calculation.cached_input_weight_scaled,
                previous_usage_size=calculation.previous_size,
                current_usage_size=calculation.current_size,
                cached_tokens=calculation.cached_tokens,
                uncached_tokens=calculation.uncached_tokens,
                effective_tokens_scaled=calculation.effective_tokens_scaled,
                calculated_credits=calculated_credits,
                deducted_credits=deducted_credits,
                settlement_mode=settlement_mode,
                status=status,
                non_charge_reason=non_charge_reason,
                created_at=now,
            )
            self.connection.commit()
        except Exception as exc:
            if not is_unique_violation(exc):
                raise
            self.connection.rollback()
            existing = self.repo.get_usage_record(turn_id)
            if existing is None:
                raise
            return existing

        record = self.repo.get_usage_record(turn_id)
        if record is None:
            raise RuntimeError("Credit usage record was not persisted")
        return record

    def adjust_current_period(
        self,
        principal: Principal,
        tenant_id: str,
        *,
        amount: int,
        reason: str,
        idempotency_key: str,
        request_id: str,
        user_id: str | None = None,
    ) -> CreditLedgerEntry:
        beneficiary_user_id = self._resolve_user_scope(
            tenant_id, user_id, required=True
        )
        key = idempotency_key.strip()
        if not key:
            raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required")
        if len(key) > 255:
            raise ApiError(400, "IDEMPOTENCY_KEY_INVALID", "Idempotency-Key is too long")
        fingerprint = _adjustment_fingerprint(
            tenant_id, amount, reason, beneficiary_user_id=beneficiary_user_id
        )
        existing = self.repo.get_adjustment_by_key(tenant_id, key)
        if existing is not None:
            return self._resolve_existing_adjustment(existing, fingerprint)

        tenant_name = self.repo.tenant_name(tenant_id)
        if tenant_name is None:
            raise ApiError(404, "TENANT_NOT_FOUND", "Tenant not found")
        period, _ = self._period_and_plan(
            tenant_id, user_id=beneficiary_user_id
        )
        if amount < 0 and -amount > max(
            self.repo.ledger_balance(
                period.id, beneficiary_user_id=beneficiary_user_id
            ),
            0,
        ):
            raise ApiError(
                409,
                "CREDIT_ADJUSTMENT_EXCEEDS_BALANCE",
                "Credit deduction exceeds the available balance",
            )

        now = _now_iso()
        entry_id = f"credit_entry_{uuid4().hex}"
        try:
            self.repo.insert_ledger_entry(
                entry_id=entry_id,
                period_id=period.id,
                tenant_id=tenant_id,
                beneficiary_user_id=beneficiary_user_id,
                entry_type="manual_adjustment",
                amount=amount,
                reference_id=None,
                idempotency_key=key,
                request_fingerprint=fingerprint,
                actor_user_id=principal.user_id,
                reason=reason,
                created_at=now,
            )
            audit = AuditService(self.connection)
            audit.record(
                audit.context(principal, request_id),
                category=AuditCategory.TENANT,
                action="tenant.credit_adjustment",
                operation_type=AuditOperationType.UPDATE,
                tenant=AuditTenant(id=tenant_id, name=tenant_name),
                resource=AuditResource(type="tenant", id=tenant_id, name=tenant_name),
                metadata={
                    "amount": amount,
                    "reason": reason,
                    **(
                        {"beneficiaryUserId": beneficiary_user_id}
                        if beneficiary_user_id is not None
                        else {}
                    ),
                },
            )
            self.connection.commit()
        except Exception as exc:
            if not is_unique_violation(exc):
                raise
            self.connection.rollback()
            existing = self.repo.get_adjustment_by_key(tenant_id, key)
            if existing is None:
                raise
            return self._resolve_existing_adjustment(existing, fingerprint)

        row = self.repo.get_adjustment_by_key(tenant_id, key)
        if row is None:
            raise RuntimeError("Credit adjustment was not persisted")
        return map_ledger_entry(row)

    def list_ledger(
        self,
        tenant_id: str,
        *,
        page: int,
        page_size: int,
        user_id: str | None = None,
    ) -> tuple[list[CreditLedgerEntry], int]:
        if self.repo.tenant_name(tenant_id) is None:
            raise ApiError(404, "TENANT_NOT_FOUND", "Tenant not found")
        beneficiary_user_id = self._resolve_user_scope(
            tenant_id, user_id, required=False
        )
        return self.repo.list_ledger(
            tenant_id,
            page=page,
            page_size=page_size,
            beneficiary_user_id=beneficiary_user_id,
        )

    def _period_and_plan(
        self,
        tenant_id: str,
        *,
        user_id: str | None = None,
        now: datetime | None = None,
    ) -> tuple[CreditPeriod, Plan]:
        user_scoped = self._uses_user_credit_accounts(tenant_id)
        beneficiary_user_id = (
            self._require_default_tenant_user(user_id) if user_scoped else None
        )
        period, plan, inserted, timestamp, period_start = self._base_period_and_plan(
            tenant_id, now=now
        )
        credit_limit = _credit_limit(plan)
        if user_scoped:
            assert beneficiary_user_id is not None
            self._ensure_user_grants(
                period,
                plan,
                beneficiary_user_id,
                credit_limit=credit_limit,
                timestamp=timestamp,
            )
            if credit_limit > period.highestPlanCreditLimit:
                self.repo.update_highest_plan_credit_limit(period.id, credit_limit, timestamp)
                period = self.repo.get_period(tenant_id, period_start) or period
            return period, plan

        if inserted and credit_limit > 0:
            self.repo.insert_ledger_entry(
                entry_id=f"credit_entry_{uuid4().hex}",
                period_id=period.id,
                tenant_id=tenant_id,
                beneficiary_user_id=None,
                entry_type="monthly_grant",
                amount=credit_limit,
                reference_id=plan.id,
                idempotency_key=None,
                request_fingerprint=None,
                actor_user_id=None,
                reason=None,
                created_at=timestamp,
            )
        elif credit_limit > period.highestPlanCreditLimit:
            difference = credit_limit - period.highestPlanCreditLimit
            self.repo.insert_ledger_entry(
                entry_id=f"credit_entry_{uuid4().hex}",
                period_id=period.id,
                tenant_id=tenant_id,
                beneficiary_user_id=None,
                entry_type="upgrade_grant",
                amount=difference,
                reference_id=plan.id,
                idempotency_key=None,
                request_fingerprint=None,
                actor_user_id=None,
                reason=None,
                created_at=timestamp,
            )
            self.repo.update_highest_plan_credit_limit(period.id, credit_limit, timestamp)
            period = self.repo.get_period(tenant_id, period_start) or period
        return period, plan

    def _default_tenant_period_and_plan(
        self, *, now: datetime | None = None
    ) -> tuple[CreditPeriod, Plan]:
        tenant_id = self.settings.default_tenant_id
        period, plan, _, timestamp, period_start = self._base_period_and_plan(
            tenant_id, now=now
        )
        credit_limit = _credit_limit(plan)
        for user_id in self.repo.active_member_user_ids(tenant_id):
            self._ensure_user_grants(
                period,
                plan,
                user_id,
                credit_limit=credit_limit,
                timestamp=timestamp,
            )
        if credit_limit > period.highestPlanCreditLimit:
            self.repo.update_highest_plan_credit_limit(period.id, credit_limit, timestamp)
            period = self.repo.get_period(tenant_id, period_start) or period
        return period, plan

    def _base_period_and_plan(
        self, tenant_id: str, *, now: datetime | None = None
    ) -> tuple[CreditPeriod, Plan, bool, str, str]:
        if self.repo.tenant_name(tenant_id) is None:
            raise ApiError(404, "TENANT_NOT_FOUND", "Tenant not found")
        subscription = self.subscription_service.ensure_default_subscription(tenant_id)
        plan = self.plan_repo.get(subscription.planId)
        if plan is None:
            raise ApiError(404, "PLAN_NOT_FOUND", "Plan not found")
        credit_limit = _credit_limit(plan)
        period_start = _month_start(now).isoformat()
        timestamp = _now_iso(now)
        proposed_id = f"credit_period_{uuid4().hex}"
        inserted = self.repo.insert_period(
            period_id=proposed_id,
            tenant_id=tenant_id,
            period_start=period_start,
            highest_plan_credit_limit=credit_limit,
            now=timestamp,
        )
        period = self.repo.get_period(tenant_id, period_start)
        if period is None:
            raise RuntimeError("Credit period was not created")
        return period, plan, inserted, timestamp, period_start

    def _ensure_user_grants(
        self,
        period: CreditPeriod,
        plan: Plan,
        user_id: str,
        *,
        credit_limit: int,
        timestamp: str,
    ) -> None:
        granted = self.repo.user_granted_credits(period.id, user_id)
        if granted == 0 and credit_limit > 0:
            self.repo.insert_ledger_entry(
                entry_id=f"credit_entry_{uuid4().hex}",
                period_id=period.id,
                tenant_id=period.tenantId,
                beneficiary_user_id=user_id,
                entry_type="monthly_grant",
                amount=credit_limit,
                reference_id=plan.id,
                idempotency_key=None,
                request_fingerprint=None,
                actor_user_id=None,
                reason=None,
                created_at=timestamp,
                ignore_conflicts=True,
            )
            granted = self.repo.user_granted_credits(period.id, user_id)
        if credit_limit > granted:
            self.repo.insert_ledger_entry(
                entry_id=f"credit_entry_{uuid4().hex}",
                period_id=period.id,
                tenant_id=period.tenantId,
                beneficiary_user_id=user_id,
                entry_type="upgrade_grant",
                amount=credit_limit - granted,
                reference_id=plan.id,
                idempotency_key=None,
                request_fingerprint=None,
                actor_user_id=None,
                reason=None,
                created_at=timestamp,
            )

    def _uses_user_credit_accounts(self, tenant_id: str) -> bool:
        return tenant_id == self.settings.default_tenant_id

    def _require_default_tenant_user(self, user_id: str | None) -> str:
        if not user_id:
            raise ApiError(
                400,
                "CREDIT_USER_REQUIRED",
                "Default tenant credit operations require a user",
            )
        if not self.repo.is_active_member(self.settings.default_tenant_id, user_id):
            raise ApiError(
                404,
                "CREDIT_USER_NOT_IN_TENANT",
                "User is not an active member of the default tenant",
            )
        return user_id

    def _resolve_user_scope(
        self,
        tenant_id: str,
        user_id: str | None,
        *,
        required: bool,
    ) -> str | None:
        if self._uses_user_credit_accounts(tenant_id):
            if user_id is None and not required:
                return None
            return self._require_default_tenant_user(user_id)
        if user_id is not None:
            raise ApiError(
                400,
                "CREDIT_USER_SCOPE_UNSUPPORTED",
                "This tenant uses a shared credit pool",
            )
        return None

    @staticmethod
    def _resolve_existing_adjustment(
        existing: dict[str, object], fingerprint: str
    ) -> CreditLedgerEntry:
        if str(existing.get("request_fingerprint") or "") != fingerprint:
            raise ApiError(
                409,
                "IDEMPOTENCY_KEY_REUSED",
                "Idempotency-Key was already used with a different request",
            )
        return map_ledger_entry(existing)


def calculate_credit_usage(
    current_size: int,
    previous_size: int,
    *,
    tokens_per_credit: int,
    cached_input_weight: Decimal,
) -> CreditCalculation:
    if tokens_per_credit <= 0:
        raise ValueError("tokens_per_credit must be positive")
    weight_scaled = _cached_weight_scaled(cached_input_weight)
    current = max(int(current_size), 0)
    previous = max(int(previous_size), 0)
    cached = min(previous, current)
    uncached = max(current - previous, 0)
    effective_scaled = uncached * CALCULATION_SCALE + cached * weight_scaled
    denominator = tokens_per_credit * CALCULATION_SCALE
    calculated = (effective_scaled + denominator - 1) // denominator if effective_scaled else 0
    return CreditCalculation(
        previous_size=previous,
        current_size=current,
        cached_tokens=cached,
        uncached_tokens=uncached,
        cached_input_weight_scaled=weight_scaled,
        effective_tokens_scaled=effective_scaled,
        calculated_credits=calculated,
    )


def _cached_weight_scaled(value: Decimal) -> int:
    weight = Decimal(value)
    if weight < 0 or weight > 1:
        raise ValueError("cached_input_weight must be between 0 and 1")
    scaled = weight * CALCULATION_SCALE
    if scaled != scaled.to_integral_value():
        raise ValueError("cached_input_weight supports at most four decimal places")
    return int(scaled)


def _credit_limit(plan: Plan) -> int:
    if plan.entitlements is None:
        raise ApiError(
            409,
            "PLAN_CREDIT_ENTITLEMENT_REQUIRED",
            "Plan requires valid credit entitlements",
        )
    return plan.entitlements.monthlyCreditLimit


def _month_start(value: datetime | None = None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    return current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(value: datetime) -> datetime:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1)
    return value.replace(month=value.month + 1)


def _now_iso(value: datetime | None = None) -> str:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat()


def _adjustment_fingerprint(
    tenant_id: str,
    amount: int,
    reason: str,
    *,
    beneficiary_user_id: str | None,
) -> str:
    fingerprint_fields = {
        "tenantId": tenant_id,
        "amount": amount,
        "reason": reason,
    }
    if beneficiary_user_id is not None:
        fingerprint_fields["beneficiaryUserId"] = beneficiary_user_id
    payload = json.dumps(
        fingerprint_fields,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
