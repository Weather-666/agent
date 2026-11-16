from __future__ import annotations

from typing import Any

from app.db import DatabaseConnection
from app.domain.credits import CreditLedgerEntry, CreditPeriod, CreditUsageRecord
from app.services._sql import execute, fetch_all, fetch_one, rowcount


class CreditRepository:
    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection

    def get_period(self, tenant_id: str, period_start: str) -> CreditPeriod | None:
        row = fetch_one(
            self.connection,
            """
            select id, tenant_id, period_start, highest_plan_credit_limit, created_at, updated_at
            from tenant_credit_periods
            where tenant_id = ? and period_start = ?
            limit 1
            """,
            (tenant_id, period_start),
        )
        return _map_period(row) if row else None

    def insert_period(
        self,
        *,
        period_id: str,
        tenant_id: str,
        period_start: str,
        highest_plan_credit_limit: int,
        now: str,
    ) -> bool:
        cursor = execute(
            self.connection,
            """
            insert into tenant_credit_periods (
              id, tenant_id, period_start, highest_plan_credit_limit, created_at, updated_at
            )
            values (?, ?, ?, ?, ?, ?)
            on conflict (tenant_id, period_start) do nothing
            """,
            (
                period_id,
                tenant_id,
                period_start,
                highest_plan_credit_limit,
                now,
                now,
            ),
        )
        return rowcount(cursor) > 0

    def update_highest_plan_credit_limit(
        self, period_id: str, highest_plan_credit_limit: int, now: str
    ) -> None:
        execute(
            self.connection,
            """
            update tenant_credit_periods
            set highest_plan_credit_limit = ?, updated_at = ?
            where id = ?
            """,
            (highest_plan_credit_limit, now, period_id),
        )

    def insert_ledger_entry(
        self,
        *,
        entry_id: str,
        period_id: str,
        tenant_id: str,
        beneficiary_user_id: str | None,
        entry_type: str,
        amount: int,
        reference_id: str | None,
        idempotency_key: str | None,
        request_fingerprint: str | None,
        actor_user_id: str | None,
        reason: str | None,
        created_at: str,
        ignore_conflicts: bool = False,
    ) -> bool:
        conflict_clause = "on conflict do nothing" if ignore_conflicts else ""
        cursor = execute(
            self.connection,
            f"""
            insert into credit_ledger (
              id, period_id, tenant_id, beneficiary_user_id, entry_type, amount, reference_id,
              idempotency_key, request_fingerprint, actor_user_id, reason, created_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            {conflict_clause}
            """,
            (
                entry_id,
                period_id,
                tenant_id,
                beneficiary_user_id,
                entry_type,
                amount,
                reference_id,
                idempotency_key,
                request_fingerprint,
                actor_user_id,
                reason,
                created_at,
            ),
        )
        return rowcount(cursor) > 0

    def get_adjustment_by_key(
        self, tenant_id: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        return fetch_one(
            self.connection,
            """
            select id, period_id, tenant_id, beneficiary_user_id, entry_type, amount, reference_id,
                   idempotency_key, request_fingerprint, actor_user_id, reason, created_at
            from credit_ledger
            where tenant_id = ? and idempotency_key = ?
            limit 1
            """,
            (tenant_id, idempotency_key),
        )

    def ledger_balance(self, period_id: str, *, beneficiary_user_id: str | None = None) -> int:
        if beneficiary_user_id is None:
            scope_sql = "beneficiary_user_id is null"
            params = (period_id,)
        else:
            scope_sql = "beneficiary_user_id = ?"
            params = (period_id, beneficiary_user_id)
        row = fetch_one(
            self.connection,
            f"""
            select coalesce(sum(amount), 0) as balance
            from credit_ledger
            where period_id = ? and {scope_sql}
            """,
            params,
        )
        return int(row["balance"]) if row else 0

    def summary_sums(
        self,
        period_id: str,
        *,
        beneficiary_user_id: str | None = None,
    ) -> dict[str, int]:
        if beneficiary_user_id is None:
            ledger_scope_sql = "beneficiary_user_id is null"
            ledger_params = (period_id,)
            usage_scope_sql = ""
            usage_params = (period_id,)
        else:
            ledger_scope_sql = "beneficiary_user_id = ?"
            ledger_params = (period_id, beneficiary_user_id)
            usage_scope_sql = "and user_id = ?"
            usage_params = (period_id, beneficiary_user_id)
        ledger = fetch_one(
            self.connection,
            f"""
            select
              coalesce(sum(case when entry_type in ('monthly_grant', 'upgrade_grant')
                                then amount else 0 end), 0) as granted_credits,
              coalesce(sum(case when entry_type = 'manual_adjustment'
                                then amount else 0 end), 0) as adjustment_credits,
              coalesce(sum(case when entry_type = 'turn_charge'
                                then -amount else 0 end), 0) as deducted_credits,
              coalesce(sum(amount), 0) as ledger_balance
            from credit_ledger
            where period_id = ? and {ledger_scope_sql}
            """,
            ledger_params,
        ) or {}
        usage = fetch_one(
            self.connection,
            f"""
            select coalesce(sum(calculated_credits), 0) as estimated_used_credits
            from credit_usage_records
            where period_id = ? {usage_scope_sql}
            """,
            usage_params,
        ) or {}
        return {
            "granted_credits": int(ledger.get("granted_credits") or 0),
            "adjustment_credits": int(ledger.get("adjustment_credits") or 0),
            "deducted_credits": int(ledger.get("deducted_credits") or 0),
            "ledger_balance": int(ledger.get("ledger_balance") or 0),
            "estimated_used_credits": int(usage.get("estimated_used_credits") or 0),
        }

    def user_granted_credits(self, period_id: str, user_id: str) -> int:
        row = fetch_one(
            self.connection,
            """
            select coalesce(sum(amount), 0) as granted_credits
            from credit_ledger
            where period_id = ?
              and beneficiary_user_id = ?
              and entry_type in ('monthly_grant', 'upgrade_grant')
            """,
            (period_id, user_id),
        )
        return int(row["granted_credits"]) if row else 0

    def list_ledger(
        self,
        tenant_id: str,
        *,
        page: int,
        page_size: int,
        beneficiary_user_id: str | None = None,
    ) -> tuple[list[CreditLedgerEntry], int]:
        user_filter = ""
        params: tuple[Any, ...] = (tenant_id,)
        if beneficiary_user_id is not None:
            user_filter = "and beneficiary_user_id = ?"
            params = (tenant_id, beneficiary_user_id)
        total_row = fetch_one(
            self.connection,
            f"""
            select count(*) as count from credit_ledger
            where tenant_id = ? {user_filter}
            """,
            params,
        )
        rows = fetch_all(
            self.connection,
            f"""
            select id, period_id, tenant_id, beneficiary_user_id, entry_type, amount, reference_id,
                   idempotency_key, actor_user_id, reason, created_at
            from credit_ledger
            where tenant_id = ? {user_filter}
            order by created_at desc, id desc
            limit ? offset ?
            """,
            (*params, page_size, (page - 1) * page_size),
        )
        return [_map_ledger_entry(row) for row in rows], int(total_row["count"] if total_row else 0)

    def get_turn_for_settlement(self, turn_id: str) -> dict[str, Any] | None:
        return fetch_one(
            self.connection,
            """
            select id, session_id, tenant_id, user_id, status, token_used,
                   token_usage_scope, token_usage_session_id,
                   token_usage_previous_snapshot, token_usage_snapshot, is_internal
            from chat_turns
            where id = ?
            limit 1
            """,
            (turn_id,),
        )

    def get_usage_record(self, turn_id: str) -> CreditUsageRecord | None:
        row = fetch_one(
            self.connection,
            """
            select id, turn_id, period_id, tenant_id, user_id, session_id, token_used,
                   usage_source, calculator_version, tokens_per_credit, rounding_mode,
                   token_usage_scope, acp_session_id, calculation_scale,
                   cached_input_weight_scaled, previous_usage_size, current_usage_size,
                   cached_tokens, uncached_tokens, effective_tokens_scaled,
                   calculated_credits, deducted_credits, settlement_mode, status,
                   non_charge_reason, created_at
            from credit_usage_records
            where turn_id = ?
            limit 1
            """,
            (turn_id,),
        )
        return _map_usage_record(row) if row else None

    def insert_usage_record(
        self,
        *,
        record_id: str,
        turn_id: str,
        period_id: str,
        tenant_id: str,
        user_id: str,
        session_id: str,
        token_used: int,
        usage_source: str,
        calculator_version: str,
        tokens_per_credit: int,
        rounding_mode: str,
        token_usage_scope: str,
        acp_session_id: str | None,
        calculation_scale: int,
        cached_input_weight_scaled: int,
        previous_usage_size: int,
        current_usage_size: int,
        cached_tokens: int,
        uncached_tokens: int,
        effective_tokens_scaled: int,
        calculated_credits: int,
        deducted_credits: int,
        settlement_mode: str,
        status: str,
        non_charge_reason: str | None,
        created_at: str,
    ) -> None:
        execute(
            self.connection,
            """
            insert into credit_usage_records (
              id, turn_id, period_id, tenant_id, user_id, session_id, token_used,
              usage_source, calculator_version, tokens_per_credit, rounding_mode,
              token_usage_scope, acp_session_id, calculation_scale,
              cached_input_weight_scaled, previous_usage_size, current_usage_size,
              cached_tokens, uncached_tokens, effective_tokens_scaled,
              calculated_credits, deducted_credits, settlement_mode, status,
              non_charge_reason, created_at
            )
            values (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                record_id,
                turn_id,
                period_id,
                tenant_id,
                user_id,
                session_id,
                token_used,
                usage_source,
                calculator_version,
                tokens_per_credit,
                rounding_mode,
                token_usage_scope,
                acp_session_id,
                calculation_scale,
                cached_input_weight_scaled,
                previous_usage_size,
                current_usage_size,
                cached_tokens,
                uncached_tokens,
                effective_tokens_scaled,
                calculated_credits,
                deducted_credits,
                settlement_mode,
                status,
                non_charge_reason,
                created_at,
            ),
        )

    def tenant_name(self, tenant_id: str) -> str | None:
        row = fetch_one(
            self.connection,
            "select name from tenants where id = ? limit 1",
            (tenant_id,),
        )
        return str(row["name"]) if row else None

    def active_member_user_ids(self, tenant_id: str) -> list[str]:
        rows = fetch_all(
            self.connection,
            """
            select tm.user_id
            from tenant_members tm
            inner join users u on u.id = tm.user_id
            inner join tenants t on t.id = tm.tenant_id
            where tm.tenant_id = ? and u.status = 'active' and t.status = 'active'
            order by tm.created_at asc, tm.user_id asc
            """,
            (tenant_id,),
        )
        return [str(row["user_id"]) for row in rows]

    def is_active_member(self, tenant_id: str, user_id: str) -> bool:
        return fetch_one(
            self.connection,
            """
            select 1
            from tenant_members tm
            inner join users u on u.id = tm.user_id
            inner join tenants t on t.id = tm.tenant_id
            where tm.tenant_id = ? and tm.user_id = ?
              and u.status = 'active' and t.status = 'active'
            limit 1
            """,
            (tenant_id, user_id),
        ) is not None


def _map_period(row: dict[str, Any]) -> CreditPeriod:
    return CreditPeriod(
        id=str(row["id"]),
        tenantId=str(row["tenant_id"]),
        periodStart=str(row["period_start"]),
        highestPlanCreditLimit=int(row["highest_plan_credit_limit"]),
        createdAt=str(row["created_at"]),
        updatedAt=str(row["updated_at"]),
    )


def map_ledger_entry(row: dict[str, Any]) -> CreditLedgerEntry:
    return _map_ledger_entry(row)


def _map_ledger_entry(row: dict[str, Any]) -> CreditLedgerEntry:
    return CreditLedgerEntry(
        id=str(row["id"]),
        periodId=str(row["period_id"]),
        tenantId=str(row["tenant_id"]),
        beneficiaryUserId=(
            str(row["beneficiary_user_id"])
            if row.get("beneficiary_user_id") is not None
            else None
        ),
        entryType=str(row["entry_type"]),
        amount=int(row["amount"]),
        referenceId=str(row["reference_id"]) if row.get("reference_id") is not None else None,
        idempotencyKey=(
            str(row["idempotency_key"]) if row.get("idempotency_key") is not None else None
        ),
        actorUserId=(
            str(row["actor_user_id"]) if row.get("actor_user_id") is not None else None
        ),
        reason=str(row["reason"]) if row.get("reason") is not None else None,
        createdAt=str(row["created_at"]),
    )


def _map_usage_record(row: dict[str, Any]) -> CreditUsageRecord:
    return CreditUsageRecord(
        id=str(row["id"]),
        turnId=str(row["turn_id"]),
        periodId=str(row["period_id"]),
        tenantId=str(row["tenant_id"]),
        userId=str(row["user_id"]),
        sessionId=str(row["session_id"]),
        tokenUsed=int(row["token_used"]),
        usageSource=str(row["usage_source"]),
        calculatorVersion=str(row["calculator_version"]),
        tokensPerCredit=int(row["tokens_per_credit"]),
        roundingMode=str(row["rounding_mode"]),
        tokenUsageScope=(
            str(row["token_usage_scope"])
            if row.get("token_usage_scope") is not None
            else None
        ),
        acpSessionId=(
            str(row["acp_session_id"]) if row.get("acp_session_id") is not None else None
        ),
        calculationScale=_optional_int(row, "calculation_scale"),
        cachedInputWeightScaled=_optional_int(row, "cached_input_weight_scaled"),
        previousUsageSize=_optional_int(row, "previous_usage_size"),
        currentUsageSize=_optional_int(row, "current_usage_size"),
        cachedTokens=_optional_int(row, "cached_tokens"),
        uncachedTokens=_optional_int(row, "uncached_tokens"),
        effectiveTokensScaled=_optional_int(row, "effective_tokens_scaled"),
        calculatedCredits=int(row["calculated_credits"]),
        deductedCredits=int(row["deducted_credits"]),
        settlementMode=str(row["settlement_mode"]),
        status=str(row["status"]),
        nonChargeReason=(
            str(row["non_charge_reason"]) if row.get("non_charge_reason") is not None else None
        ),
        createdAt=str(row["created_at"]),
    )


def _optional_int(row: dict[str, Any], key: str) -> int | None:
    value = row.get(key)
    return int(value) if value is not None else None
