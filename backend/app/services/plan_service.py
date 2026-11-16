from __future__ import annotations

from uuid import uuid4

from app.core.errors import ApiError
from app.db import DatabaseConnection
from app.domain.audit import AuditCategory, AuditOperationType, AuditResource
from app.domain.auth import Principal
from app.domain.plans import (
    CreatePlanRequest,
    Plan,
    ReplacePlanEntitlementsRequest,
    ReplacePlanExpertsRequest,
    ReplacePlanPricesRequest,
    UpdatePlanRequest,
)
from app.services._sql import is_unique_violation
from app.services.audit_service import AuditService, changes
from app.services.plan_repository import PlanRepository
from app.services.subscription_repository import SubscriptionRepository


CORE_PLAN_CODES = {
    "plan_free": "free",
    "plan_pro": "pro",
    "plan_max": "max",
    "plan_business": "business",
}


class PlanService:
    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection
        self.repo = PlanRepository(connection)
        self.subscription_repo = SubscriptionRepository(connection)

    def list(self) -> list[Plan]:
        return self.repo.list()

    def list_market(self) -> list[Plan]:
        return self.repo.list(active_only=True)

    def get(self, plan_id: str) -> Plan:
        plan = self.repo.get(plan_id)
        if not plan:
            raise ApiError(404, "PLAN_NOT_FOUND", "Plan not found")
        return plan

    def create(
        self,
        principal: Principal,
        request: CreatePlanRequest,
        *,
        request_id: str,
    ) -> Plan:
        plan_id = f"plan_{uuid4().hex}"
        code = (
            _normalize_code(request.code)
            if request.code is not None
            else self._generate_code_from_type_label(request.typeLabel)
        )
        localized_content = _localized_content(request.localizedContent)
        if request.status == "active":
            _require_publishable_localized_content(localized_content)
        try:
            if request.isRecommended:
                self.repo.clear_recommended_except()
            self.repo.insert(
                plan_id=plan_id,
                code=code,
                name=request.name,
                level=request.level,
                description=request.description,
                type_label=request.typeLabel,
                subtitle=request.subtitle,
                badge_label=request.badgeLabel,
                highlight_items=_unique_strings(request.highlightItems),
                localized_content=localized_content,
                upgrade_rules=request.upgradeRules,
                status=request.status,
                is_recommended=request.isRecommended,
                sort_order=request.sortOrder,
            )
            audit = AuditService(self.connection)
            audit.record(
                audit.context(principal, request_id),
                category=AuditCategory.PLAN,
                action="plan.create",
                operation_type=AuditOperationType.CREATE,
                resource=AuditResource(type="plan", id=plan_id, name=request.name),
                metadata={"code": code, "level": request.level, "status": request.status},
            )
            self.connection.commit()
        except Exception as exc:
            if is_unique_violation(exc):
                raise ApiError(409, "PLAN_CONFLICT", "Plan code or level already exists") from exc
            raise
        return self.get(plan_id)

    def update(
        self,
        principal: Principal,
        plan_id: str,
        request: UpdatePlanRequest,
        *,
        request_id: str,
    ) -> Plan:
        current = self.get(plan_id)
        next_recommended = (
            request.isRecommended if request.isRecommended is not None else current.isRecommended
        )
        next_code = self._resolve_update_code(plan_id, current, request)
        fixed_code = CORE_PLAN_CODES.get(plan_id)
        if fixed_code is not None and next_code != fixed_code:
            raise ApiError(409, "CORE_PLAN_CODE_IMMUTABLE", "Core plan code cannot be changed")
        next_localized_content = (
            _localized_content(request.localizedContent)
            if request.localizedContent is not None
            else current.localizedContent
        )
        next_status = request.status if request.status is not None else current.status
        if current.status != "active" and next_status == "active":
            _require_publishable_localized_content(next_localized_content)
        try:
            if next_recommended:
                self.repo.clear_recommended_except(plan_id)
            self.repo.update(
                plan_id,
                code=next_code,
                name=request.name if request.name is not None else current.name,
                level=request.level if request.level is not None else current.level,
                description=(
                    request.description if request.description is not None else current.description
                ),
                type_label=request.typeLabel
                if request.typeLabel is not None
                else current.typeLabel,
                subtitle=request.subtitle if request.subtitle is not None else current.subtitle,
                badge_label=(
                    request.badgeLabel if request.badgeLabel is not None else current.badgeLabel
                ),
                highlight_items=(
                    _unique_strings(request.highlightItems)
                    if request.highlightItems is not None
                    else current.highlightItems
                ),
                localized_content=next_localized_content,
                upgrade_rules=(
                    request.upgradeRules
                    if request.upgradeRules is not None
                    else current.upgradeRules
                ),
                status=next_status,
                is_recommended=next_recommended,
                sort_order=request.sortOrder
                if request.sortOrder is not None
                else current.sortOrder,
            )
            updated = self.get(plan_id)
            before_state = _plan_audit_state(current)
            after_state = _plan_audit_state(updated)
            before_state["upgradeRulesChanged"] = False
            after_state["upgradeRulesChanged"] = current.upgradeRules != updated.upgradeRules
            event_changes = changes(
                before_state,
                after_state,
                {
                    "code",
                    "name",
                    "level",
                    "description",
                    "typeLabel",
                    "subtitle",
                    "badgeLabel",
                    "highlightItems",
                    "localizedContent",
                    "upgradeRuleKeys",
                    "upgradeRulesChanged",
                    "status",
                    "isRecommended",
                    "sortOrder",
                },
            )
            if event_changes:
                audit = AuditService(self.connection)
                audit.record(
                    audit.context(principal, request_id),
                    category=AuditCategory.PLAN,
                    action="plan.update",
                    operation_type=AuditOperationType.UPDATE,
                    resource=AuditResource(type="plan", id=updated.id, name=updated.name),
                    changes=event_changes,
                )
            self.connection.commit()
        except Exception as exc:
            if is_unique_violation(exc):
                raise ApiError(409, "PLAN_CONFLICT", "Plan code or level already exists") from exc
            raise
        return self.get(plan_id)

    def _resolve_update_code(self, plan_id: str, current: Plan, request: UpdatePlanRequest) -> str:
        if request.code is not None:
            return _normalize_code(request.code)
        if plan_id in CORE_PLAN_CODES:
            return current.code
        if request.typeLabel is not None and request.typeLabel != current.typeLabel:
            return self._generate_code_from_type_label(request.typeLabel, current_plan_id=plan_id)
        return current.code

    def _generate_code_from_type_label(
        self, type_label: str | None, *, current_plan_id: str | None = None
    ) -> str:
        if not type_label:
            raise ApiError(400, "PLAN_TYPE_LABEL_REQUIRED", "Plan typeLabel is required")
        base_code = _base_code_for_type_label(type_label)
        candidate = base_code
        suffix = 2
        while True:
            owner_id = self.repo.plan_id_by_code(candidate)
            if owner_id is None or owner_id == current_plan_id:
                return candidate
            candidate = f"{base_code}_{suffix}"
            suffix += 1

    def replace_prices(
        self,
        principal: Principal,
        plan_id: str,
        request: ReplacePlanPricesRequest,
        *,
        request_id: str,
    ) -> Plan:
        current = self.get(plan_id)
        seen = set()
        configured_currency: str | None = None
        prices = []
        for item in request.items:
            currency = item.currency.strip().upper()
            if currency not in {"CNY", "USD"}:
                raise ApiError(400, "PLAN_PRICE_CURRENCY_INVALID", "Currency must be CNY or USD")
            key = item.billingPeriod
            if key in seen:
                raise ApiError(409, "PLAN_PRICE_DUPLICATE", "Duplicate plan price")
            seen.add(key)
            if item.billingPeriod in {"monthly", "yearly"}:
                if configured_currency is not None and configured_currency != currency:
                    raise ApiError(400, "PLAN_PRICE_CURRENCY_MISMATCH", "Monthly and yearly prices must use the same currency")
                configured_currency = currency
            prices.append(
                {
                    "billing_period": item.billingPeriod,
                    "currency": currency,
                    "amount_cents": item.amountCents,
                    "discount_label": item.discountLabel,
                    "is_enabled": item.isEnabled,
                }
            )
        self.repo.replace_prices(plan_id, prices)
        updated = self.get(plan_id)
        event_changes = changes(
            {"prices": _prices_audit_state(current)},
            {"prices": _prices_audit_state(updated)},
            {"prices"},
        )
        if event_changes:
            audit = AuditService(self.connection)
            audit.record(
                audit.context(principal, request_id),
                category=AuditCategory.PLAN,
                action="plan.prices_replace",
                operation_type=AuditOperationType.UPDATE,
                resource=AuditResource(type="plan", id=current.id, name=current.name),
                changes=event_changes,
            )
        self.connection.commit()
        return updated

    def replace_entitlements(
        self,
        principal: Principal,
        plan_id: str,
        request: ReplacePlanEntitlementsRequest,
        *,
        request_id: str,
    ) -> Plan:
        current = self.get(plan_id)
        current_entitlements = current.entitlements
        personal_library_quota = (
            current_entitlements.personalLibraryQuotaBytes
            if current_entitlements is not None
            else 2 * 1024**3
        )
        team_library_quota = (
            current_entitlements.teamLibraryQuotaBytes if current_entitlements is not None else 0
        )
        team_library_enabled = (
            current_entitlements.teamLibraryEnabled if current_entitlements is not None else False
        )
        self.repo.replace_entitlements(
            plan_id,
            monthly_credit_limit=request.monthlyCreditLimit,
            all_experts=request.allExperts,
            seat_limit=request.seatLimit,
            personal_library_quota_bytes=(
                request.personalLibraryQuotaBytes
                if request.personalLibraryQuotaBytes is not None
                else personal_library_quota
            ),
            team_library_quota_bytes=(
                request.teamLibraryQuotaBytes
                if request.teamLibraryQuotaBytes is not None
                else team_library_quota
            ),
            team_library_enabled=(
                request.teamLibraryEnabled
                if request.teamLibraryEnabled is not None
                else team_library_enabled
            ),
            single_turn_token_limit=request.singleTurnTokenLimit,
            model_tiers=_unique_strings(request.modelTiers),
            features=request.features,
        )
        updated = self.get(plan_id)
        if updated.entitlements and updated.entitlements.teamLibraryEnabled:
            self.subscription_repo.record_team_library_entitlements_for_plan(
                plan_id, updated.entitlements.teamLibraryQuotaBytes
            )
        before_entitlements = _entitlements_audit_state(current)
        after_entitlements = _entitlements_audit_state(updated)
        if before_entitlements is not None and after_entitlements is not None:
            before_entitlements["featuresChanged"] = False
            after_entitlements["featuresChanged"] = (
                current.entitlements.features != updated.entitlements.features
                if current.entitlements and updated.entitlements
                else False
            )
        event_changes = changes(
            {"entitlements": before_entitlements},
            {"entitlements": after_entitlements},
            {"entitlements"},
        )
        if event_changes:
            audit = AuditService(self.connection)
            audit.record(
                audit.context(principal, request_id),
                category=AuditCategory.PLAN,
                action="plan.entitlements_replace",
                operation_type=AuditOperationType.UPDATE,
                resource=AuditResource(type="plan", id=current.id, name=current.name),
                changes=event_changes,
            )
        self.connection.commit()
        return updated

    def replace_experts(
        self,
        principal: Principal,
        plan_id: str,
        request: ReplacePlanExpertsRequest,
        *,
        request_id: str,
    ) -> Plan:
        current = self.get(plan_id)
        expert_ids = _unique_strings(request.expertIds)
        existing = self.repo.existing_expert_ids(expert_ids)
        missing = [eid for eid in expert_ids if eid not in existing]
        if missing:
            raise ApiError(404, "EXPERT_NOT_FOUND", "Expert not found", {"expertIds": missing})
        self.repo.replace_experts(plan_id, expert_ids)
        event_changes = changes(
            {"expertIds": current.expertIds},
            {"expertIds": expert_ids},
            {"expertIds"},
        )
        if event_changes:
            audit = AuditService(self.connection)
            audit.record(
                audit.context(principal, request_id),
                category=AuditCategory.PLAN,
                action="plan.experts_replace",
                operation_type=AuditOperationType.UPDATE,
                resource=AuditResource(type="plan", id=current.id, name=current.name),
                changes=event_changes,
            )
        self.connection.commit()
        return self.get(plan_id)

    def delete(
        self,
        principal: Principal,
        plan_id: str,
        *,
        request_id: str,
    ) -> None:
        plan = self.get(plan_id)
        if plan_id in CORE_PLAN_CODES:
            raise ApiError(409, "CORE_PLAN_DELETE_FORBIDDEN", "Core plans cannot be deleted")
        if self.repo.has_subscriptions(plan_id):
            raise ApiError(409, "PLAN_HAS_SUBSCRIPTIONS", "Plan has subscriptions")
        if self.repo.delete(plan_id) <= 0:
            raise ApiError(404, "PLAN_NOT_FOUND", "Plan not found")
        audit = AuditService(self.connection)
        audit.record(
            audit.context(principal, request_id),
            category=AuditCategory.PLAN,
            action="plan.delete",
            operation_type=AuditOperationType.DELETE,
            resource=AuditResource(type="plan", id=plan.id, name=plan.name),
            metadata={"code": plan.code, "level": plan.level, "status": plan.status},
        )
        self.connection.commit()


def _normalize_code(value: str) -> str:
    return value.strip().lower()


def _base_code_for_type_label(type_label: str) -> str:
    normalized = type_label.strip().lower()
    mapping = {
        "免费版": "free",
        "免费": "free",
        "free": "free",
        "默认套餐": "default",
        "默认": "default",
        "default": "default",
        "个人付费": "pro",
        "专业版": "pro",
        "pro": "pro",
        "paid": "pro",
        "团队": "business",
        "business": "business",
        "business 版": "business",
        "企业定制": "enterprise",
        "enterprise": "enterprise",
    }
    code = mapping.get(normalized)
    if code is None:
        raise ApiError(400, "PLAN_TYPE_LABEL_UNSUPPORTED", "Unsupported plan typeLabel")
    return code


def _unique_strings(values: list[str]) -> list[str]:
    return [value for value in dict.fromkeys(values) if value]


def _localized_content(value: dict[str, object]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for locale in ("zh", "en"):
        item = value.get(locale)
        if item is None:
            continue
        raw = item.model_dump() if hasattr(item, "model_dump") else item
        if not isinstance(raw, dict):
            continue
        result[locale] = {
            "subtitle": _optional_text(raw.get("subtitle")),
            "description": _optional_text(raw.get("description")),
            "badgeLabel": _optional_text(raw.get("badgeLabel")),
            "highlightItems": _unique_strings(
                [str(entry).strip() for entry in raw.get("highlightItems", []) if str(entry).strip()]
            ) if isinstance(raw.get("highlightItems"), list) else [],
        }
    return result


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _require_publishable_localized_content(content: dict[str, dict[str, object]]) -> None:
    for locale in ("zh", "en"):
        item = content.get(locale)
        if not item or not item.get("subtitle") or not item.get("description") or not item.get("highlightItems"):
            raise ApiError(
                400,
                "PLAN_LOCALIZATION_INCOMPLETE",
                "Chinese and English subtitle, description, and highlights are required before publishing",
            )


def _plan_audit_state(plan: Plan) -> dict[str, object]:
    return {
        "code": plan.code,
        "name": plan.name,
        "level": plan.level,
        "description": plan.description,
        "typeLabel": plan.typeLabel,
        "subtitle": plan.subtitle,
        "badgeLabel": plan.badgeLabel,
        "highlightItems": plan.highlightItems,
        "localizedContent": {
            locale: item.model_dump() for locale, item in plan.localizedContent.items()
        },
        "upgradeRuleKeys": sorted(plan.upgradeRules),
        "status": plan.status,
        "isRecommended": plan.isRecommended,
        "sortOrder": plan.sortOrder,
    }


def _prices_audit_state(plan: Plan) -> list[dict[str, object]]:
    return [
        {
            "billingPeriod": item.billingPeriod,
            "currency": item.currency,
            "amountCents": item.amountCents,
            "discountLabel": item.discountLabel,
            "isEnabled": item.isEnabled,
        }
        for item in plan.prices
    ]


def _entitlements_audit_state(plan: Plan) -> dict[str, object] | None:
    item = plan.entitlements
    if item is None:
        return None
    return {
        "monthlyCreditLimit": item.monthlyCreditLimit,
        "allExperts": item.allExperts,
        "seatLimit": item.seatLimit,
        "singleTurnTokenLimit": item.singleTurnTokenLimit,
        "modelTiers": item.modelTiers,
        "featureKeys": sorted(item.features),
    }
