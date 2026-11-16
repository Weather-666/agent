from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_acp_gateway_client
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import hash_password
from app.db import migrate_database, open_database_connection
from app.domain.auth import Principal, TenantRole
from app.domain.chat import ChatTurnRequest, CreateSessionRequest
from app.main import create_app
from app.services.chat_repository import ChatRepository
from app.services.chat_service import ChatService, _AcpTurnResult
from app.services.credit_service import CreditService, calculate_credit_usage
from app.services.expert_access_service import ExpertAccessService


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'credits.sqlite3'}",
        database_schema_dir=str(Path(__file__).resolve().parents[1] / "infra" / "sql"),
        jwt_secret="test-secret-with-at-least-32-bytes",
    )


def _seed_user_tenant(
    settings: Settings,
    *,
    user_id: str = "user_credit",
    tenant_id: str = "tenant_credit",
    email: str = "credit@example.com",
    password: str = "credit-secret",
    plan_id: str = "plan_free",
    platform_admin: bool = False,
) -> None:
    with open_database_connection(settings) as connection:
        connection.execute(
            """
            insert into users (id, email, password_hash, name, status)
            values (?, ?, ?, ?, 'active')
            """,
            (user_id, email, hash_password(password), user_id),
        )
        connection.execute(
            """
            insert into tenants (id, type, name, slug, owner_user_id, status)
            values (?, 'personal', ?, ?, ?, 'active')
            """,
            (tenant_id, tenant_id, tenant_id, user_id),
        )
        connection.execute(
            """
            insert into tenant_members (id, tenant_id, user_id, role)
            values (?, ?, ?, 'admin')
            """,
            (f"member_{user_id}", tenant_id, user_id),
        )
        connection.execute(
            """
            insert into subscriptions (
              id, tenant_id, plan_id, status, billing_period, current_period_start
            )
            values (?, ?, ?, 'active', ?, ?)
            """,
            (
                f"subscription_{tenant_id}",
                tenant_id,
                plan_id,
                "free" if plan_id == "plan_free" else "monthly",
                datetime.now(UTC).isoformat(),
            ),
        )
        if platform_admin:
            connection.execute(
                """
                insert into platform_user_roles (id, user_id, role)
                values (?, ?, 'admin')
                """,
                (f"platform_role_{user_id}", user_id),
            )
        connection.commit()


def _seed_default_tenant_user(
    settings: Settings,
    *,
    user_id: str,
    email: str,
    password: str,
) -> None:
    with open_database_connection(settings) as connection:
        connection.execute(
            """
            insert into users (id, email, password_hash, name, status)
            values (?, ?, ?, ?, 'active')
            """,
            (user_id, email, hash_password(password), user_id),
        )
        connection.execute(
            """
            insert into tenant_members (id, tenant_id, user_id, role)
            values (?, 'tenant_default', ?, 'member')
            """,
            (f"member_{user_id}", user_id),
        )
        connection.commit()


def _insert_turn(
    connection,
    *,
    turn_id: str,
    tenant_id: str = "tenant_credit",
    user_id: str = "user_credit",
    session_id: str = "session_credit",
    status: str = "completed",
    token_used: int = 0,
    token_usage_scope: str = "no_search",
    token_usage_session_id: str = "acp_credit",
    token_usage_previous_snapshot: int = 0,
    token_usage_snapshot: int | None = None,
    is_internal: bool = False,
) -> None:
    current_snapshot = token_used if token_usage_snapshot is None else token_usage_snapshot
    connection.execute(
        """
        insert into chat_sessions (
          id, tenant_id, user_id, title, status, is_pinned, created_at, updated_at
        )
        values (?, ?, ?, 'Credits', 'active', false, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        on conflict (id) do nothing
        """,
        (session_id, tenant_id, user_id),
    )
    connection.execute(
        """
        insert into chat_turns (
          id, session_id, tenant_id, user_id, request_text, status,
          token_usage_scope, token_usage_session_id, token_usage_previous_snapshot,
          token_usage_snapshot, token_used, is_internal, created_at, completed_at
        )
        values (
          ?, ?, ?, ?, 'question', ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        """,
        (
            turn_id,
            session_id,
            tenant_id,
            user_id,
            status,
            token_usage_scope,
            token_usage_session_id,
            token_usage_previous_snapshot,
            current_snapshot,
            token_used,
            is_internal,
        ),
    )
    connection.commit()


def _login_headers(
    client: TestClient, email: str, password: str, *, tenant_id: str | None = None
) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    headers = {"Authorization": f"Bearer {response.json()['accessToken']}"}
    if tenant_id:
        headers["x-tenant-id"] = tenant_id
    return headers


def test_credit_calculator_boundaries() -> None:
    assert [
        calculate_credit_usage(
            value,
            0,
            tokens_per_credit=500,
            cached_input_weight=Decimal("0.1"),
        ).calculated_credits
        for value in (0, 1, 499, 500, 501)
    ] == [0, 1, 1, 1, 2]


def test_estimated_cache_v2_calculator_split_and_exact_rounding() -> None:
    first = calculate_credit_usage(
        500, 0, tokens_per_credit=500, cached_input_weight=Decimal("0.1")
    )
    growth = calculate_credit_usage(
        1_400, 1_000, tokens_per_credit=500, cached_input_weight=Decimal("0.1")
    )
    no_growth = calculate_credit_usage(
        500, 500, tokens_per_credit=500, cached_input_weight=Decimal("0.1")
    )
    shrink = calculate_credit_usage(
        400, 1_000, tokens_per_credit=500, cached_input_weight=Decimal("0.1")
    )
    just_over = calculate_credit_usage(
        1_401, 1_000, tokens_per_credit=500, cached_input_weight=Decimal("0.1")
    )

    assert (first.cached_tokens, first.uncached_tokens, first.calculated_credits) == (0, 500, 1)
    assert (growth.cached_tokens, growth.uncached_tokens, growth.effective_tokens_scaled) == (
        1_000,
        400,
        5_000_000,
    )
    assert growth.calculated_credits == 1
    assert (no_growth.effective_tokens_scaled, no_growth.calculated_credits) == (500_000, 1)
    assert (shrink.cached_tokens, shrink.uncached_tokens, shrink.calculated_credits) == (
        400,
        0,
        1,
    )
    assert just_over.calculated_credits == 2


def test_credit_calculator_settings_defaults_env_override_and_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EXPERT_CREDIT_TOKENS_PER_CREDIT", raising=False)
    monkeypatch.delenv("EXPERT_CREDIT_CACHED_INPUT_WEIGHT", raising=False)
    defaults = Settings(_env_file=None)
    assert defaults.credit_tokens_per_credit == 500
    assert defaults.credit_cached_input_weight == Decimal("0.1")

    monkeypatch.setenv("EXPERT_CREDIT_TOKENS_PER_CREDIT", "1000")
    monkeypatch.setenv("EXPERT_CREDIT_CACHED_INPUT_WEIGHT", "0.25")
    overridden = Settings(_env_file=None)
    assert overridden.credit_tokens_per_credit == 1_000
    assert overridden.credit_cached_input_weight == Decimal("0.25")
    assert calculate_credit_usage(
        1_000,
        1_000,
        tokens_per_credit=overridden.credit_tokens_per_credit,
        cached_input_weight=overridden.credit_cached_input_weight,
    ).calculated_credits == 1

    with pytest.raises(ValueError):
        Settings(_env_file=None, credit_tokens_per_credit=0)
    with pytest.raises(ValueError):
        Settings(_env_file=None, credit_cached_input_weight="1.01")
    with pytest.raises(ValueError):
        Settings(_env_file=None, credit_cached_input_weight="0.12345")


def test_credit_env_example_has_v2_settings_without_legacy_enforcement() -> None:
    example = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    assert "EXPERT_CREDIT_TOKENS_PER_CREDIT=500" in example
    assert "EXPERT_CREDIT_CACHED_INPUT_WEIGHT=0.1" in example
    assert "EXPERT_CREDIT_ENFORCEMENT_ENABLED" not in example


def test_acp_session_change_resets_usage_baseline() -> None:
    result = _AcpTurnResult(
        bound_session_id="acp_old",
        previous_usage_snapshot=800,
    )
    result.bind_session("acp_new")
    result.capture_usage(600)

    assert result.previous_usage_size == 0
    assert result.token_usage_snapshot == 600
    assert result.token_used == 600


def test_schema_core_plans_and_repeat_migration_preserve_data(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    migrate_database(settings)
    _seed_user_tenant(settings)

    with open_database_connection(settings) as connection:
        rows = connection.execute(
            "select id, code, prices, entitlements, expert_ids from plans order by level"
        ).fetchall()
        assert [(row["id"], row["code"]) for row in rows] == [
            ("plan_free", "free"),
            ("plan_pro", "pro"),
            ("plan_max", "max"),
            ("plan_business", "business"),
        ]
        entitlements = [json.loads(row["entitlements"]) for row in rows]
        assert [item["monthlyCreditLimit"] for item in entitlements] == [
            2_000,
            20_000,
            50_000,
            130_000,
        ]
        assert [item["allExperts"] for item in entitlements] == [False, False, True, True]
        assert json.loads(rows[0]["expert_ids"]) == ["1825107e997dfde2"]
        assert json.loads(rows[1]["expert_ids"]) == ["1825107e997dfde2"]
        business_prices = json.loads(rows[3]["prices"])
        assert [(item["billingPeriod"], item["amountCents"]) for item in business_prices] == [
            ("yearly", 238_800)
        ]
        connection.execute("update plans set expert_ids = '[]' where id = 'plan_free'")
        connection.execute(
            "update plans set expert_ids = '[\"expert_custom\"]' where id = 'plan_pro'"
        )
        connection.execute("update plans set name = 'Free Customized' where id = 'plan_free'")
        connection.execute(
            """
            insert into plans (
              id, code, name, level, description, prices, entitlements,
              expert_ids, status, is_recommended, sort_order
            ) values (
              'plan_default', 'default', 'Legacy Default', 1, 'Legacy plan', '[]',
              '{"monthlyQuestionLimit":100,"monthlyTokenLimit":100000,"seatLimit":1}',
              '[]', 'active', false, 1
            )
            """
        )
        CreditService(connection, settings).get_current_summary("tenant_credit")
        connection.commit()

    migrate_database(settings)

    with open_database_connection(settings) as connection:
        assert connection.execute(
            "select name from plans where id = 'plan_free'"
        ).fetchone()["name"] == "Free Customized"
        assert connection.execute(
            "select name from plans where id = 'plan_default'"
        ).fetchone()["name"] == "Legacy Default"
        core_expert_ids = connection.execute(
            "select id, expert_ids from plans where id in ('plan_free', 'plan_pro') order by level"
        ).fetchall()
        assert [json.loads(row["expert_ids"]) for row in core_expert_ids] == [
            ["1825107e997dfde2"],
            ["expert_custom"],
        ]
        assert connection.execute("select count(*) as count from subscriptions").fetchone()[
            "count"
        ] == 1
        assert connection.execute(
            "select count(*) as count from tenant_credit_periods"
        ).fetchone()["count"] == 1
        assert connection.execute("select count(*) as count from credit_ledger").fetchone()[
            "count"
        ] == 1


def test_repeat_migration_repairs_legacy_duplicate_running_turns(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    migrate_database(settings)
    _seed_user_tenant(settings)

    with open_database_connection(settings) as connection:
        connection.execute("drop index uq_chat_turns_session_running")
        connection.execute(
            """
            insert into chat_sessions (
              id, tenant_id, user_id, title, status, is_pinned, created_at, updated_at
            ) values (
              'session_legacy_running', 'tenant_credit', 'user_credit', 'Legacy', 'active', false,
              CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        )
        for turn_id, created_at in [
            ("turn_running_old", "2026-08-20T00:00:00+00:00"),
            ("turn_running_new", "2026-08-20T00:00:01+00:00"),
        ]:
            connection.execute(
                """
                insert into chat_turns (
                  id, session_id, tenant_id, user_id, request_text, status, created_at
                ) values (
                  ?, 'session_legacy_running', 'tenant_credit', 'user_credit', 'legacy',
                  'running', ?
                )
                """,
                (turn_id, created_at),
            )
        connection.commit()

    migrate_database(settings)
    migrate_database(settings)

    with open_database_connection(settings) as connection:
        rows = connection.execute(
            """
            select id, status, stop_reason, completed_at
            from chat_turns
            where session_id = 'session_legacy_running'
            order by created_at asc
            """
        ).fetchall()
        assert [(row["id"], row["status"]) for row in rows] == [
            ("turn_running_old", "cancelled"),
            ("turn_running_new", "running"),
        ]
        assert rows[0]["stop_reason"] == "superseded"
        assert rows[0]["completed_at"] is not None


def test_migration_seeds_reserved_default_expert_when_legacy_id_exists(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    migrate_database(settings)

    with open_database_connection(settings) as connection:
        connection.execute(
            "update experts set id = 'expert_default' where id = '1825107e997dfde2'"
        )
        connection.execute(
            "update plans set expert_ids = '[]' where id in ('plan_free', 'plan_pro')"
        )
        connection.commit()

    migrate_database(settings)

    with open_database_connection(settings) as connection:
        reserved = connection.execute(
            "select status from experts where id = '1825107e997dfde2'"
        ).fetchone()
        plans = connection.execute(
            "select expert_ids from plans where id in ('plan_free', 'plan_pro') order by level"
        ).fetchall()

    assert reserved is not None
    assert reserved["status"] == "unlisted"
    assert [json.loads(row["expert_ids"]) for row in plans] == [
        ["1825107e997dfde2"],
        ["1825107e997dfde2"],
    ]


def test_migration_replaces_legacy_level_conflict_and_seeds_all_core_plans(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    migrate_database(settings)
    _seed_user_tenant(settings)

    with open_database_connection(settings) as connection:
        connection.execute("delete from subscriptions")
        connection.execute("delete from plans")
        connection.execute(
            """
            insert into plans (
              id, code, name, level, description, prices, entitlements,
              expert_ids, status, is_recommended, sort_order
            ) values (
              'plan_default', 'default', 'Legacy Default', 10, 'Legacy plan', '[]',
              '{"monthlyQuestionLimit":100,"monthlyTokenLimit":100000,"seatLimit":1}',
              '[]', 'active', true, 10
            )
            """
        )
        connection.execute(
            """
            insert into subscriptions (
              id, tenant_id, plan_id, status, billing_period, current_period_start
            ) values (
              'subscription_legacy', 'tenant_credit', 'plan_default', 'active', 'free', ?
            )
            """,
            (datetime.now(UTC).isoformat(),),
        )
        connection.commit()

    migrate_database(settings)

    with open_database_connection(settings) as connection:
        rows = connection.execute("select id, code, level from plans order by level").fetchall()
        assert [tuple(row) for row in rows] == [
            ("plan_free", "free", 10),
            ("plan_pro", "pro", 20),
            ("plan_max", "max", 30),
            ("plan_business", "business", 40),
        ]
        assert connection.execute("select count(*) as count from subscriptions").fetchone()[
            "count"
        ] == 0
        summary = CreditService(connection, settings).get_current_summary("tenant_credit")
        assert (summary.planId, summary.monthlyCreditLimit) == ("plan_free", 2_000)

    migrate_database(settings)

    with open_database_connection(settings) as connection:
        assert connection.execute("select count(*) as count from plans").fetchone()["count"] == 4
        assert connection.execute("select count(*) as count from subscriptions").fetchone()[
            "count"
        ] == 1


def test_period_grant_upgrade_downgrade_and_cross_month(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    migrate_database(settings)
    _seed_user_tenant(settings)
    august = datetime(2026, 8, 13, 10, tzinfo=UTC)
    september = datetime(2026, 9, 2, 10, tzinfo=UTC)

    with open_database_connection(settings) as connection:
        service = CreditService(connection, settings)
        initial = service.get_current_summary("tenant_credit", now=august)
        assert initial.monthlyCreditLimit == 2_000
        assert initial.grantedCredits == 2_000
        assert initial.remainingCredits == 2_000

        connection.execute(
            "update subscriptions set plan_id = 'plan_pro', billing_period = 'monthly' where tenant_id = ?",
            ("tenant_credit",),
        )
        upgraded = service.get_current_summary("tenant_credit", now=august)
        assert upgraded.grantedCredits == 20_000
        assert upgraded.remainingCredits == 20_000

        connection.execute(
            "update subscriptions set plan_id = 'plan_free', billing_period = 'free' where tenant_id = ?",
            ("tenant_credit",),
        )
        downgraded = service.get_current_summary("tenant_credit", now=august)
        assert downgraded.monthlyCreditLimit == 20_000
        assert downgraded.remainingCredits == 20_000

        connection.execute(
            "update subscriptions set plan_id = 'plan_pro', billing_period = 'monthly' where tenant_id = ?",
            ("tenant_credit",),
        )
        repeated = service.get_current_summary("tenant_credit", now=august)
        assert repeated.grantedCredits == 20_000
        assert connection.execute(
            "select count(*) as count from credit_ledger where entry_type = 'upgrade_grant'"
        ).fetchone()["count"] == 1

        pro = json.loads(
            connection.execute(
                "select entitlements from plans where id = 'plan_pro'"
            ).fetchone()["entitlements"]
        )
        pro["monthlyCreditLimit"] = 25_000
        connection.execute(
            "update plans set entitlements = ? where id = 'plan_pro'",
            (json.dumps(pro),),
        )
        edited_up = service.get_current_summary("tenant_credit", now=august)
        assert edited_up.grantedCredits == 25_000
        assert edited_up.remainingCredits == 25_000

        pro["monthlyCreditLimit"] = 22_000
        connection.execute(
            "update plans set entitlements = ? where id = 'plan_pro'",
            (json.dumps(pro),),
        )
        edited_down = service.get_current_summary("tenant_credit", now=august)
        assert edited_down.monthlyCreditLimit == 25_000
        assert edited_down.grantedCredits == 25_000
        assert edited_down.remainingCredits == 25_000

        next_month = service.get_current_summary("tenant_credit", now=september)
        assert next_month.grantedCredits == 22_000
        assert next_month.remainingCredits == 22_000
        assert connection.execute(
            "select count(*) as count from tenant_credit_periods"
        ).fetchone()["count"] == 2


def test_enforced_settlement_and_non_chargeable_reasons_are_idempotent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    migrate_database(settings)
    _seed_user_tenant(settings)

    with open_database_connection(settings) as connection:
        for turn_id, status, token_used, is_internal in [
            ("turn_chargeable", "completed", 501, False),
            ("turn_zero", "completed", 0, False),
            ("turn_failed", "failed", 500, False),
            ("turn_cancelled", "cancelled", 500, False),
            ("turn_internal", "completed", 500, True),
        ]:
            _insert_turn(
                connection,
                turn_id=turn_id,
                status=status,
                token_used=token_used,
                is_internal=is_internal,
            )
        service = CreditService(connection, settings)
        settled = service.settle_turn("turn_chargeable")
        assert (settled.status, settled.calculatedCredits, settled.deductedCredits) == (
            "settled",
            2,
            2,
        )
        assert service.settle_turn("turn_chargeable").id == settled.id
        assert (
            settled.calculatorVersion,
            settled.usageSource,
            settled.tokensPerCredit,
            settled.cachedInputWeightScaled,
            settled.calculationScale,
        ) == (
            "estimated-cache-v2",
            "acp_context_snapshot_split",
            500,
            1_000,
            10_000,
        )
        assert service.settle_turn("turn_zero").nonChargeReason == "usage_missing_or_zero"
        assert service.settle_turn("turn_failed").nonChargeReason == "turn_failed"
        assert service.settle_turn("turn_cancelled").nonChargeReason == "turn_cancelled"
        assert service.settle_turn("turn_internal").nonChargeReason == "internal_turn"
        assert connection.execute(
            "select count(*) as count from credit_usage_records"
        ).fetchone()["count"] == 5
        assert connection.execute(
            "select count(*) as count from credit_ledger where entry_type = 'turn_charge'"
        ).fetchone()["count"] == 1
        summary = service.get_current_summary("tenant_credit")
        assert summary.estimatedUsedCredits == 2
        assert summary.deductedCredits == 2
        assert summary.remainingCredits == 1_998
        assert summary.enforcementEnabled is True


def test_estimated_cache_v2_settlement_persists_replayable_audit_values(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    migrate_database(settings)
    _seed_user_tenant(settings)

    with open_database_connection(settings) as connection:
        cases = [
            ("turn_first", 0, 500, 500, 0, 500, 5_000_000),
            ("turn_growth", 1_000, 1_400, 400, 1_000, 400, 5_000_000),
            ("turn_same", 500, 500, 0, 500, 0, 500_000),
            ("turn_shrink", 1_000, 400, 0, 400, 0, 400_000),
        ]
        for turn_id, previous, current, delta, cached, uncached, _ in cases:
            _insert_turn(
                connection,
                turn_id=turn_id,
                session_id=f"session_{turn_id}",
                token_used=delta,
                token_usage_previous_snapshot=previous,
                token_usage_snapshot=current,
            )

        service = CreditService(connection, settings)
        for turn_id, previous, current, _, cached, uncached, effective_scaled in cases:
            record = service.settle_turn(turn_id)
            assert record.calculatorVersion == "estimated-cache-v2"
            assert record.usageSource == "acp_context_snapshot_split"
            assert record.roundingMode == "ceil"
            assert record.tokenUsageScope == "no_search"
            assert record.acpSessionId == "acp_credit"
            assert record.previousUsageSize == previous
            assert record.currentUsageSize == current
            assert record.cachedTokens == cached
            assert record.uncachedTokens == uncached
            assert record.effectiveTokensScaled == effective_scaled
            assert record.calculatedCredits == 1
            assert service.settle_turn(turn_id).id == record.id

        assert connection.execute(
            "select count(*) as count from credit_ledger where entry_type = 'turn_charge'"
        ).fetchone()["count"] == len(cases)


def test_enforced_settlement_caps_charge_and_blocks_next_turn(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    migrate_database(settings)
    _seed_user_tenant(settings)

    with open_database_connection(settings) as connection:
        free = json.loads(
            connection.execute(
                "select entitlements from plans where id = 'plan_free'"
            ).fetchone()["entitlements"]
        )
        free["monthlyCreditLimit"] = 2
        connection.execute(
            "update plans set entitlements = ? where id = 'plan_free'",
            (json.dumps(free),),
        )
        _insert_turn(connection, turn_id="turn_enforced", token_used=1_001)
        _insert_turn(connection, turn_id="turn_after_zero", token_used=499)
        service = CreditService(connection, settings)
        settled = service.settle_turn("turn_enforced")
        assert (settled.calculatedCredits, settled.deductedCredits, settled.status) == (
            3,
            2,
            "settled",
        )
        with pytest.raises(ApiError) as exhausted:
            service.ensure_turn_allowed("tenant_credit")
        assert (exhausted.value.status_code, exhausted.value.code) == (402, "CREDIT_EXHAUSTED")
        after_zero = service.settle_turn("turn_after_zero")
        assert (after_zero.calculatedCredits, after_zero.deductedCredits) == (1, 0)
        summary = service.get_current_summary("tenant_credit", admin=True)
        assert summary.remainingCredits == 0
        assert summary.ledgerBalance == 0
        assert summary.deductedCredits == 2


def test_default_tenant_credit_balances_are_isolated_per_user(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    migrate_database(settings)
    _seed_default_tenant_user(
        settings,
        user_id="default_user_a",
        email="default-a@example.com",
        password="default-a-secret",
    )
    _seed_default_tenant_user(
        settings,
        user_id="default_user_b",
        email="default-b@example.com",
        password="default-b-secret",
    )

    with open_database_connection(settings) as connection:
        free = json.loads(
            connection.execute(
                "select entitlements from plans where id = 'plan_free'"
            ).fetchone()["entitlements"]
        )
        free["monthlyCreditLimit"] = 2
        connection.execute(
            "update plans set entitlements = ? where id = 'plan_free'",
            (json.dumps(free),),
        )
        connection.commit()
        _insert_turn(
            connection,
            turn_id="turn_default_a",
            tenant_id="tenant_default",
            user_id="default_user_a",
            session_id="session_default_a",
            token_used=1_001,
        )

        service = CreditService(connection, settings)
        user_a_before = service.get_current_summary(
            "tenant_default", user_id="default_user_a"
        )
        user_b_before = service.get_current_summary(
            "tenant_default", user_id="default_user_b"
        )
        assert user_a_before.remainingCredits == 2
        assert user_b_before.remainingCredits == 2

        settled = service.settle_turn("turn_default_a")
        assert settled.deductedCredits == 2
        with pytest.raises(ApiError) as exhausted:
            service.ensure_turn_allowed("tenant_default", user_id="default_user_a")
        assert (exhausted.value.status_code, exhausted.value.code) == (
            402,
            "CREDIT_EXHAUSTED",
        )
        service.ensure_turn_allowed("tenant_default", user_id="default_user_b")

        user_a_after = service.get_current_summary(
            "tenant_default", user_id="default_user_a", admin=True
        )
        user_b_after = service.get_current_summary(
            "tenant_default", user_id="default_user_b", admin=True
        )
        aggregate = service.get_current_summary("tenant_default", admin=True)
        assert (user_a_after.remainingCredits, user_a_after.deductedCredits) == (0, 2)
        assert (user_b_after.remainingCredits, user_b_after.deductedCredits) == (2, 0)
        assert aggregate.monthlyCreditLimit == 4
        assert aggregate.grantedCredits == 4
        assert aggregate.deductedCredits == 2
        assert aggregate.remainingCredits == 2

        ledger = connection.execute(
            """
            select beneficiary_user_id, entry_type, amount
            from credit_ledger
            where tenant_id = 'tenant_default'
            order by beneficiary_user_id, entry_type
            """
        ).fetchall()
        assert [tuple(row) for row in ledger] == [
            ("default_user_a", "monthly_grant", 2),
            ("default_user_a", "turn_charge", -2),
            ("default_user_b", "monthly_grant", 2),
        ]
        assert connection.execute(
            "select count(*) as count from tenant_credit_periods where tenant_id = 'tenant_default'"
        ).fetchone()["count"] == 1

        connection.execute(
            "update users set status = 'disabled' where id = 'default_user_b'"
        )
        connection.commit()
        active_aggregate = service.get_current_summary("tenant_default", admin=True)
        assert active_aggregate.monthlyCreditLimit == 2
        assert active_aggregate.grantedCredits == 2
        assert active_aggregate.deductedCredits == 2
        assert active_aggregate.remainingCredits == 0
        with pytest.raises(ApiError) as disabled_user:
            service.get_current_summary(
                "tenant_default", user_id="default_user_b", admin=True
            )
        assert disabled_user.value.code == "CREDIT_USER_NOT_IN_TENANT"


def test_default_tenant_admin_credit_operations_require_target_user(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        _seed_default_tenant_user(
            settings,
            user_id="default_user_a",
            email="default-a@example.com",
            password="default-a-secret",
        )
        _seed_default_tenant_user(
            settings,
            user_id="default_user_b",
            email="default-b@example.com",
            password="default-b-secret",
        )
        _seed_user_tenant(
            settings,
            user_id="platform_admin",
            tenant_id="tenant_admin",
            email="admin@example.com",
            password="admin-secret",
            platform_admin=True,
        )
        user_a_headers = _login_headers(
            client,
            "default-a@example.com",
            "default-a-secret",
            tenant_id="tenant_default",
        )
        user_b_headers = _login_headers(
            client,
            "default-b@example.com",
            "default-b-secret",
            tenant_id="tenant_default",
        )
        admin_headers = _login_headers(client, "admin@example.com", "admin-secret")

        assert client.get("/api/v1/credits/current", headers=user_a_headers).json()[
            "remainingCredits"
        ] == 2_000
        assert client.get("/api/v1/credits/current", headers=user_b_headers).json()[
            "remainingCredits"
        ] == 2_000

        aggregate = client.get(
            "/api/v1/tenants/tenant_default/credits/current",
            headers=admin_headers,
        )
        assert aggregate.status_code == 200
        assert aggregate.json()["monthlyCreditLimit"] == 4_000
        assert aggregate.json()["remainingCredits"] == 4_000

        missing_user = client.post(
            "/api/v1/tenants/tenant_default/credits/adjustments",
            headers={**admin_headers, "Idempotency-Key": "default-adjustment-missing-user"},
            json={"amount": 50, "reason": "target required"},
        )
        assert (missing_user.status_code, missing_user.json()["code"]) == (
            400,
            "CREDIT_USER_REQUIRED",
        )

        adjusted = client.post(
            "/api/v1/tenants/tenant_default/credits/adjustments?userId=default_user_a",
            headers={**admin_headers, "Idempotency-Key": "default-adjustment-user-a"},
            json={"amount": 50, "reason": "user grant"},
        )
        assert adjusted.status_code == 200, adjusted.text
        assert adjusted.json()["beneficiaryUserId"] == "default_user_a"

        user_a = client.get("/api/v1/credits/current", headers=user_a_headers)
        user_b = client.get("/api/v1/credits/current", headers=user_b_headers)
        assert user_a.json()["remainingCredits"] == 2_050
        assert user_b.json()["remainingCredits"] == 2_000

        user_a_ledger = client.get(
            "/api/v1/tenants/tenant_default/credits/ledger"
            "?userId=default_user_a&page=1&pageSize=10",
            headers=admin_headers,
        )
        assert user_a_ledger.status_code == 200
        assert user_a_ledger.json()["total"] == 2
        assert {
            item["beneficiaryUserId"] for item in user_a_ledger.json()["items"]
        } == {"default_user_a"}

        with open_database_connection(settings) as connection:
            audit = connection.execute(
                """
                select metadata from audit_events
                where action = 'tenant.credit_adjustment'
                  and tenant_id = 'tenant_default'
                limit 1
                """
            ).fetchone()
        assert audit is not None
        assert json.loads(audit["metadata"])["beneficiaryUserId"] == "default_user_a"


def test_cancelled_turn_cannot_be_overwritten_by_stream_completion(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    migrate_database(settings)
    _seed_user_tenant(settings)

    with open_database_connection(settings) as connection:
        repo = ChatRepository(connection)
        connection.execute(
            """
            insert into chat_sessions (
              id, tenant_id, user_id, title, status, is_pinned, created_at, updated_at
            ) values ('session_race', 'tenant_credit', 'user_credit', 'Race', 'active', false,
                      CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
        repo.create_turn(
            turn_id="turn_race",
            session_id="session_race",
            tenant_id="tenant_credit",
            user_id="user_credit",
            request_text="race",
            model=None,
            query_rewrite=False,
            multi_hop_config=None,
            token_usage_scope="no_search",
            runtime_identity=None,
            now=datetime.now(UTC).isoformat(),
        )
        assert repo.cancel_running_turn("turn_race", datetime.now(UTC).isoformat()) is True
        assert repo.finalize_turn(
            turn_id="turn_race",
            status="completed",
            response_text="done",
            reasoning_text="",
            stop_reason="end_turn",
            error_message=None,
            token_usage_session_id="acp_race",
            token_usage_previous_snapshot=0,
            token_usage_snapshot=500,
            token_used=500,
            completed_at=datetime.now(UTC).isoformat(),
        ) is False
        row = connection.execute(
            "select status, response_text, token_used from chat_turns where id = 'turn_race'"
        ).fetchone()
        assert (row["status"], row["response_text"], row["token_used"]) == (
            "cancelled",
            None,
            0,
        )


def test_usage_baseline_isolated_by_scope_and_acp_session(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    migrate_database(settings)
    _seed_user_tenant(settings)

    with open_database_connection(settings) as connection:
        for turn_id, scope, acp_session_id, snapshot, status in [
            ("turn_default_a", "no_search", "acp_default_a", 500, "completed"),
            ("turn_search", "search", "acp_search", 900, "completed"),
            ("turn_default_b", "no_search", "acp_default_b", 700, "completed"),
            ("turn_failed", "no_search", "acp_default_a", 999, "failed"),
        ]:
            _insert_turn(
                connection,
                turn_id=turn_id,
                token_used=snapshot,
                token_usage_scope=scope,
                token_usage_session_id=acp_session_id,
                token_usage_snapshot=snapshot,
                status=status,
            )
        _insert_turn(
            connection,
            turn_id="turn_pre_v2_untagged",
            session_id="session_pre_v2_untagged",
            token_used=321,
            token_usage_session_id="",
            token_usage_snapshot=321,
        )

        repo = ChatRepository(connection)

        def baseline(scope: str, acp_session_id: str) -> int | None:
            return repo.get_token_usage_baseline(
                session_id="session_credit",
                tenant_id="tenant_credit",
                user_id="user_credit",
                token_usage_scope=scope,
                token_usage_session_id=acp_session_id,
            )

        assert baseline("no_search", "acp_default_a") == 500
        assert baseline("no_search", "acp_default_b") == 700
        assert baseline("search", "acp_search") == 900
        assert baseline("no_search", "acp_unknown") is None
        assert repo.get_token_usage_baseline(
            session_id="session_pre_v2_untagged",
            tenant_id="tenant_credit",
            user_id="user_credit",
            token_usage_scope="no_search",
            token_usage_session_id="acp_current_but_unproven",
        ) is None


def test_expert_access_all_whitelist_and_old_session_recheck(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    migrate_database(settings)
    _seed_user_tenant(settings)
    default_expert_id = "1825107e997dfde2"
    restricted_expert_id = "expert_limited"
    principal = Principal(
        user_id="user_credit",
        email="credit@example.com",
        active_tenant_id="tenant_credit",
        tenant_roles=[TenantRole.ADMIN],
        tenant_permissions=["chat:ask"],
    )

    with open_database_connection(settings) as connection:
        access = ExpertAccessService(connection)
        assert access.current_access("tenant_credit").allows(default_expert_id) is True
        with pytest.raises(ApiError) as denied:
            access.require_access("tenant_credit", restricted_expert_id)
        assert denied.value.code == "EXPERT_NOT_INCLUDED_IN_PLAN"

        connection.execute(
            """
            insert into chat_sessions (
              id, tenant_id, user_id, title, expert_id, runtime_type,
              status, is_pinned, created_at, updated_at
            ) values ('session_expert', 'tenant_credit', 'user_credit', 'Expert', ?, 'codex',
                      'active', false, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (default_expert_id,),
        )
        connection.execute(
            "update plans set expert_ids = '[]' where id = 'plan_free'"
        )
        connection.commit()
        chat = ChatService(connection, settings=settings)
        with pytest.raises(ApiError) as old_session_denied:
            chat.validate_turn_preconditions(
                principal,
                "session_expert",
                ChatTurnRequest(question="after downgrade"),
            )
        assert old_session_denied.value.code == "EXPERT_NOT_INCLUDED_IN_PLAN"

        connection.execute(
            "update subscriptions set plan_id = 'plan_max', billing_period = 'monthly' "
            "where tenant_id = 'tenant_credit'"
        )
        assert access.current_access("tenant_credit").allows("future_expert") is True


def test_credit_api_permissions_idempotency_audit_and_tenant_contract(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        _seed_user_tenant(settings)
        _seed_user_tenant(
            settings,
            user_id="platform_admin",
            tenant_id="tenant_admin",
            email="admin@example.com",
            password="admin-secret",
            platform_admin=True,
        )
        user_headers = _login_headers(
            client,
            "credit@example.com",
            "credit-secret",
            tenant_id="tenant_credit",
        )
        admin_headers = _login_headers(client, "admin@example.com", "admin-secret")

        current = client.get("/api/v1/credits/current", headers=user_headers)
        assert current.status_code == 200, current.text
        assert current.json()["remainingCredits"] == 2_000
        assert current.json()["enforcementEnabled"] is True

        mismatch_headers = dict(user_headers)
        mismatch_headers["x-tenant-id"] = "tenant_admin"
        assert client.get("/api/v1/credits/current", headers=mismatch_headers).status_code == 403
        assert client.get(
            "/api/v1/tenants/tenant_credit/credits/current", headers=user_headers
        ).status_code == 403

        adjustment_headers = {**admin_headers, "Idempotency-Key": "adjustment-1"}
        adjusted = client.post(
            "/api/v1/tenants/tenant_credit/credits/adjustments",
            headers=adjustment_headers,
            json={"amount": 50, "reason": "  support grant  "},
        )
        assert adjusted.status_code == 200, adjusted.text
        assert adjusted.json()["reason"] == "support grant"
        repeated = client.post(
            "/api/v1/tenants/tenant_credit/credits/adjustments",
            headers=adjustment_headers,
            json={"amount": 50, "reason": "support grant"},
        )
        assert repeated.status_code == 200
        assert repeated.json()["id"] == adjusted.json()["id"]
        conflict = client.post(
            "/api/v1/tenants/tenant_credit/credits/adjustments",
            headers=adjustment_headers,
            json={"amount": 51, "reason": "support grant"},
        )
        assert (conflict.status_code, conflict.json()["code"]) == (409, "IDEMPOTENCY_KEY_REUSED")
        too_much = client.post(
            "/api/v1/tenants/tenant_credit/credits/adjustments",
            headers={**admin_headers, "Idempotency-Key": "adjustment-2"},
            json={"amount": -3_000, "reason": "invalid deduction"},
        )
        assert (too_much.status_code, too_much.json()["code"]) == (
            409,
            "CREDIT_ADJUSTMENT_EXCEEDS_BALANCE",
        )
        assert client.post(
            "/api/v1/tenants/tenant_credit/credits/adjustments",
            headers={**admin_headers, "Idempotency-Key": "adjustment-zero"},
            json={"amount": 0, "reason": "zero"},
        ).status_code == 422

        ledger = client.get(
            "/api/v1/tenants/tenant_credit/credits/ledger?page=1&pageSize=10",
            headers=admin_headers,
        )
        assert ledger.status_code == 200
        assert ledger.json()["total"] == 2
        assert {item["entryType"] for item in ledger.json()["items"]} == {
            "monthly_grant",
            "manual_adjustment",
        }

        upgraded = client.patch(
            "/api/v1/tenants/tenant_credit/subscription",
            headers=admin_headers,
            json={"planId": "plan_pro", "billingPeriod": "monthly"},
        )
        assert upgraded.status_code == 200, upgraded.text
        assert upgraded.json()["currentPlan"]["code"] == "pro"
        assert upgraded.json()["monthlyCredits"]["monthlyCreditLimit"] == 20_000
        assert upgraded.json()["monthlyCredits"]["remainingCredits"] == 20_050

        downgraded = client.patch(
            "/api/v1/tenants/tenant_credit/subscription",
            headers=admin_headers,
            json={"planId": "plan_free", "billingPeriod": "free"},
        )
        assert downgraded.status_code == 200, downgraded.text
        assert downgraded.json()["monthlyCredits"]["monthlyCreditLimit"] == 20_000
        assert downgraded.json()["monthlyCredits"]["remainingCredits"] == 20_050

        tenants = client.get("/api/v1/tenants", headers=admin_headers)
        assert tenants.status_code == 200
        item = next(item for item in tenants.json()["items"] if item["id"] == "tenant_credit")
        assert "monthlyCredits" in item
        assert "monthlyUsage" not in item
        users = client.get("/api/v1/users", headers=admin_headers)
        assert users.status_code == 200
        assert all("monthlyUsage" not in item for item in users.json()["items"])

        with open_database_connection(settings) as connection:
            audit = connection.execute(
                """
                select request_id, metadata from audit_events
                where action = 'tenant.credit_adjustment'
                """
            ).fetchall()
            assert len(audit) == 1
            assert json.loads(audit[0]["metadata"]) == {
                "amount": 50,
                "reason": "support grant",
            }
            subscription_audits = connection.execute(
                "select count(*) as count from audit_events "
                "where action = 'tenant.subscription_change' and tenant_id = 'tenant_credit'"
            ).fetchone()
            assert subscription_audits["count"] == 2


def test_custom_plan_without_credit_entitlements_cannot_be_assigned(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        _seed_user_tenant(
            settings,
            user_id="platform_admin",
            tenant_id="tenant_admin",
            email="admin@example.com",
            password="admin-secret",
            platform_admin=True,
        )
        admin_headers = _login_headers(client, "admin@example.com", "admin-secret")
        created = client.post(
            "/api/v1/plans",
            headers=admin_headers,
            json={
                "code": "custom-no-credits",
                "name": "No Credits",
                "level": 90,
                "description": "Missing entitlements",
            },
        )
        assert created.status_code == 201, created.text
        plan_id = created.json()["id"]
        prices = client.put(
            f"/api/v1/plans/{plan_id}/prices",
            headers=admin_headers,
            json={
                "items": [
                    {
                        "billingPeriod": "free",
                        "currency": "USD",
                        "amountCents": 0,
                        "isEnabled": True,
                    }
                ]
            },
        )
        assert prices.status_code == 200
        response = client.patch(
            "/api/v1/tenants/tenant_admin/subscription",
            headers=admin_headers,
            json={"planId": plan_id, "billingPeriod": "free"},
        )
        assert (response.status_code, response.json()["code"]) == (
            409,
            "PLAN_CREDIT_ENTITLEMENT_REQUIRED",
        )


def test_openapi_credit_contract_and_removed_usage_fields(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    schema = create_app(settings).openapi()
    paths = schema["paths"]
    assert "/api/v1/credits/current" in paths
    assert "/api/v1/tenants/{tenant_id}/credits/current" in paths
    assert "/api/v1/tenants/{tenant_id}/credits/ledger" in paths
    assert "/api/v1/tenants/{tenant_id}/credits/adjustments" in paths
    entitlements = schema["components"]["schemas"]["PlanEntitlements"]["properties"]
    assert "monthlyCreditLimit" in entitlements
    assert "allExperts" in entitlements
    assert "monthlyQuestionLimit" not in entitlements
    assert "monthlyTokenLimit" not in entitlements
    assert "monthlyCredits" in schema["components"]["schemas"]["Tenant"]["properties"]
    assert "monthlyUsage" not in schema["components"]["schemas"]["Tenant"]["properties"]
    assert "monthlyUsage" not in schema["components"]["schemas"]["UserSummary"]["properties"]
    assert "isAccessible" in schema["components"]["schemas"]["ExpertMarketExpert"]["properties"]
    assert "CREDIT_EXHAUSTED" in paths["/api/v1/chat/sessions/{session_id}/turns"]["post"][
        "responses"
    ]["402"]["description"]
    assert "CHAT_TURN_ALREADY_RUNNING" in paths[
        "/api/v1/chat/sessions/{session_id}/turns"
    ]["post"]["responses"]["409"]["description"]
    adjustment_description = paths[
        "/api/v1/tenants/{tenant_id}/credits/adjustments"
    ]["post"]["responses"]["409"]["description"]
    assert "IDEMPOTENCY_KEY_REUSED" in adjustment_description
    adjustment_parameters = paths[
        "/api/v1/tenants/{tenant_id}/credits/adjustments"
    ]["post"]["parameters"]
    idempotency_parameter = next(
        item for item in adjustment_parameters if item["name"] == "Idempotency-Key"
    )
    assert idempotency_parameter["in"] == "header"
    assert idempotency_parameter["required"] is True
    user_parameter = next(item for item in adjustment_parameters if item["name"] == "userId")
    assert user_parameter["in"] == "query"
    assert user_parameter["required"] is False
    assert "beneficiaryUserId" in schema["components"]["schemas"]["CreditLedgerEntry"][
        "properties"
    ]
    assert "credit_enforcement_enabled" not in Settings.model_fields


class _FakeAcp:
    route_prefix = ""
    search_route_prefix = None
    default_model = None

    def prepare_default_cwd(self) -> None:
        return None

    def prepare_tenant_cwd(self, tenant_id: str) -> str:
        return f"/tmp/{tenant_id}"

    def prepare_user_cwd(self, tenant_id: str, user_id: str) -> str:
        return f"/tmp/{tenant_id}/users/{user_id}"

    async def list_sessions(self, **kwargs) -> dict:
        return {"sessions": [], "next_cursor": ""}

    def stream_turn(self, **kwargs):
        async def events():
            yield "event: session"
            yield 'data: {"session_id": "acp_credit"}'
            yield ""
            yield "event: usage"
            yield 'data: {"data": {"sessionUpdate": "usage_update", "used": 501}}'
            yield ""
            yield "event: delta"
            yield 'data: {"text": "ok"}'
            yield ""
            yield "event: done"
            yield 'data: {"stop_reason": "end_turn"}'
            yield ""

        return events()


def test_same_session_running_turn_has_database_guard_and_stable_conflict(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    migrate_database(settings)
    _seed_user_tenant(settings)
    principal = Principal(
        user_id="user_credit",
        email="credit@example.com",
        active_tenant_id="tenant_credit",
        tenant_roles=[TenantRole.ADMIN],
        tenant_permissions=["chat:ask"],
    )

    with open_database_connection(settings) as connection:
        connection.execute(
            """
            insert into chat_sessions (
              id, tenant_id, user_id, title, status, is_pinned, created_at, updated_at
            ) values (
              'session_running_guard', 'tenant_credit', 'user_credit', 'Guard', 'active', false,
              CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()
        service = ChatService(connection, acp=_FakeAcp(), settings=settings)  # type: ignore[arg-type]
        request = ChatTurnRequest(question="first")
        first_turn_id = service.reserve_turn(principal, "session_running_guard", request)

        with pytest.raises(ApiError) as conflict:
            service.reserve_turn(principal, "session_running_guard", request)
        assert (conflict.value.status_code, conflict.value.code) == (
            409,
            "CHAT_TURN_ALREADY_RUNNING",
        )
        assert connection.execute(
            "select count(*) as count from chat_turns where session_id = 'session_running_guard'"
        ).fetchone()["count"] == 1

        assert service.repo.cancel_running_turn(first_turn_id, datetime.now(UTC).isoformat())
        connection.commit()
        assert service.reserve_turn(principal, "session_running_guard", request) != first_turn_id


def test_running_turn_conflict_is_returned_before_sse(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    fake_acp = _FakeAcp()
    app = create_app(settings)
    app.dependency_overrides[get_acp_gateway_client] = lambda: fake_acp

    with TestClient(app) as client:
        _seed_user_tenant(settings)
        headers = _login_headers(
            client,
            "credit@example.com",
            "credit-secret",
            tenant_id="tenant_credit",
        )
        session = client.post(
            "/api/v1/chat/sessions",
            headers=headers,
            json={"title": "Concurrent Turn"},
        )
        assert session.status_code == 201
        session_id = session.json()["id"]

        with open_database_connection(settings) as connection:
            service = ChatService(
                connection, acp=fake_acp, settings=settings  # type: ignore[arg-type]
            )
            service.reserve_turn(
                Principal(
                    user_id="user_credit",
                    email="credit@example.com",
                    active_tenant_id="tenant_credit",
                    tenant_roles=[TenantRole.ADMIN],
                    tenant_permissions=["chat:ask"],
                ),
                session_id,
                ChatTurnRequest(question="first"),
            )

        conflict = client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=headers,
            json={"question": "second"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "CHAT_TURN_ALREADY_RUNNING"


@pytest.mark.asyncio
async def test_team_sessions_keep_shared_workspace_mode(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    migrate_database(settings)
    _seed_user_tenant(settings)
    principal = Principal(
        user_id="user_credit",
        email="credit@example.com",
        active_tenant_id="tenant_credit",
        tenant_roles=[TenantRole.ADMIN],
        tenant_permissions=["chat:ask"],
    )

    with open_database_connection(settings) as connection:
        service = ChatService(connection, acp=_FakeAcp(), settings=settings)  # type: ignore[arg-type]
        session = await service.create_session(principal, CreateSessionRequest())
        row = service.repo.get_session_row("tenant_credit", "user_credit", session.id)

        assert row is not None
        assert json.loads(row["agent_options"]) == {}
        assert service._prepare_acp_cwd({**row, "expert_id": "expert_bound"}) == (
            "/tmp/tenant_credit"
        )


def test_migration_repoints_current_legacy_default_subscriptions_without_retrocharge(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    migrate_database(settings)
    _seed_user_tenant(settings)
    principal = Principal(
        user_id="user_credit",
        email="credit@example.com",
        active_tenant_id="tenant_credit",
        tenant_roles=[TenantRole.ADMIN],
        tenant_permissions=["chat:ask"],
    )

    with open_database_connection(settings) as connection:
        period = CreditService(connection, settings).apply_current_plan_limit("tenant_credit")
        _insert_turn(connection, turn_id="turn_legacy_shadow", token_used=501)
        connection.execute(
            """
            insert into credit_usage_records (
              id, turn_id, period_id, tenant_id, user_id, session_id, token_used,
              usage_source, calculator_version, tokens_per_credit, rounding_mode,
              calculated_credits, deducted_credits, settlement_mode, status, created_at
            ) values (
              'usage_legacy_shadow', 'turn_legacy_shadow', ?, 'tenant_credit',
              'user_credit', 'session_credit', 501, 'acp_context_positive_delta',
              'estimated-v1', 500, 'ceil', 2, 0, 'shadow', 'shadow', CURRENT_TIMESTAMP
            )
            """,
            (period.id,),
        )
        connection.execute(
            """
            insert into plans (
              id, code, name, level, description, prices, entitlements,
              expert_ids, status, is_recommended, sort_order
            ) values (
              'plan_default', 'default', 'Legacy Default', 1, 'Legacy plan', '[]',
              '{"monthlyCreditLimit":0,"allExperts":false,"seatLimit":1,"singleTurnTokenLimit":null,"modelTiers":["core"],"features":{}}',
              '[]', 'active', false, 1
            )
            """
        )
        connection.execute(
            """
            update subscriptions
            set plan_id = 'plan_default', billing_period = 'monthly',
                current_period_end = null, cancel_at_period_end = true
            where id = 'subscription_tenant_credit'
            """
        )
        connection.execute(
            """
            insert into subscriptions (
              id, tenant_id, plan_id, status, billing_period, current_period_start
            ) values (
              'subscription_legacy_cancelled', 'tenant_credit', 'plan_default',
              'cancelled', 'monthly', CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()

    migrate_database(settings)

    with open_database_connection(settings) as connection:
        current = connection.execute(
            """
            select id, plan_id, billing_period, current_period_end, cancel_at_period_end
            from subscriptions where id = 'subscription_tenant_credit'
            """
        ).fetchone()
        cancelled = connection.execute(
            "select plan_id, status from subscriptions where id = 'subscription_legacy_cancelled'"
        ).fetchone()
        usage = connection.execute(
            """
            select settlement_mode, status, calculated_credits, deducted_credits
            from credit_usage_records where id = 'usage_legacy_shadow'
            """
        ).fetchone()
        assert tuple(current) == (
            "subscription_tenant_credit",
            "plan_free",
            "free",
            None,
            0,
        )
        assert tuple(cancelled) == ("plan_default", "cancelled")
        assert tuple(usage) == ("shadow", "shadow", 2, 0)
        legacy_record = CreditService(connection, settings).repo.get_usage_record(
            "turn_legacy_shadow"
        )
        assert legacy_record is not None
        assert legacy_record.calculatorVersion == "estimated-v1"
        assert legacy_record.calculationScale is None
        assert legacy_record.cachedInputWeightScaled is None
        assert legacy_record.previousUsageSize is None
        assert legacy_record.currentUsageSize is None
        assert connection.execute(
            "select count(*) as count from credit_ledger where entry_type = 'turn_charge'"
        ).fetchone()["count"] == 0

        service = ChatService(connection, acp=_FakeAcp(), settings=settings)  # type: ignore[arg-type]
        service.validate_turn_preconditions(
            principal,
            "session_credit",
            ChatTurnRequest(question="hello"),
        )
        summary = service.credits.get_current_summary("tenant_credit")
        assert (summary.planId, summary.monthlyCreditLimit, summary.remainingCredits) == (
            "plan_free",
            2_000,
            2_000,
        )
        assert summary.enforcementEnabled is True

    migrate_database(settings)

    with open_database_connection(settings) as connection:
        assert connection.execute(
            "select count(*) as count from subscriptions"
        ).fetchone()["count"] == 2
        assert connection.execute(
            "select count(*) as count from credit_usage_records"
        ).fetchone()["count"] == 1
        assert connection.execute(
            "select count(*) as count from credit_ledger where entry_type = 'turn_charge'"
        ).fetchone()["count"] == 0


@pytest.mark.asyncio
async def test_settlement_failure_does_not_break_completed_turn_or_sse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    migrate_database(settings)
    _seed_user_tenant(settings)
    principal = Principal(
        user_id="user_credit",
        email="credit@example.com",
        active_tenant_id="tenant_credit",
        tenant_roles=[TenantRole.ADMIN],
        tenant_permissions=["chat:ask"],
    )

    with open_database_connection(settings) as connection:
        connection.execute(
            """
            insert into chat_sessions (
              id, tenant_id, user_id, title, status, is_pinned, created_at, updated_at
            ) values ('session_sse', 'tenant_credit', 'user_credit', 'SSE', 'active', false,
                      CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
        connection.commit()
        service = ChatService(connection, acp=_FakeAcp(), settings=settings)  # type: ignore[arg-type]

        def fail_settlement(turn_id: str) -> None:
            raise RuntimeError("simulated settlement failure")

        monkeypatch.setattr(service.credits, "settle_turn", fail_settlement)
        request = ChatTurnRequest(question="hello")
        turn_id = service.reserve_turn(principal, "session_sse", request)
        events = [
            event
            async for event in service.stream_turn(
                principal,
                "session_sse",
                request,
                turn_id=turn_id,
            )
        ]
        assert any(event.startswith("event: turn_completed") for event in events)
        row = connection.execute(
            "select status, token_used from chat_turns where session_id = 'session_sse'"
        ).fetchone()
        assert (row["status"], row["token_used"]) == ("completed", 501)


def test_core_plan_code_and_delete_guards(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        _seed_user_tenant(
            settings,
            user_id="platform_admin",
            tenant_id="tenant_admin",
            email="admin@example.com",
            password="admin-secret",
            platform_admin=True,
        )
        headers = _login_headers(client, "admin@example.com", "admin-secret")
        changed = client.patch(
            "/api/v1/plans/plan_free",
            headers=headers,
            json={"code": "free-renamed"},
        )
        assert (changed.status_code, changed.json()["code"]) == (
            409,
            "CORE_PLAN_CODE_IMMUTABLE",
        )
        deleted = client.delete("/api/v1/plans/plan_max", headers=headers)
        assert (deleted.status_code, deleted.json()["code"]) == (
            409,
            "CORE_PLAN_DELETE_FORBIDDEN",
        )
