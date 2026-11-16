from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from app.db import DatabaseConnection
from app.domain.experts import SYSTEM_DEFAULT_EXPERT_ID, Expert, ExpertMarketExpert
from app.services._sql import execute, fetch_all, fetch_one, json_param, rowcount


class ExpertRepository:
    """Raw SQL data access for experts and their skill / knowledge-base links."""

    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection

    def list(
        self,
        *,
        name: str | None = None,
        category_id: str | None = None,
        status: str | None = None,
    ) -> list[Expert]:
        where = []
        params: list[Any] = []
        if name:
            where.append("lower(e.name) like ?")
            params.append(f"%{name.casefold()}%")
        if category_id:
            where.append("e.category_id = ?")
            params.append(category_id)
        if status:
            where.append("e.status = ?")
            params.append(status)
        where_sql = f"where {' and '.join(where)}" if where else ""
        rows = fetch_all(
            self.connection,
            f"""
            {_EXPERT_SELECT}
            {where_sql}
            order by e.created_at desc, e.id asc
            """,
            params,
        )
        return self._map_experts(rows)

    def get(self, expert_id: str) -> Expert | None:
        row = fetch_one(
            self.connection,
            f"""
            {_EXPERT_SELECT}
            where e.id = ?
            limit 1
            """,
            (expert_id,),
        )
        if not row:
            return None
        return self._map_experts([row])[0]

    def expert_id_exists(self, expert_id: str) -> bool:
        return (
            fetch_one(
                self.connection,
                "select id from experts where id = ? limit 1",
                (expert_id,),
            )
            is not None
        )

    def list_market(self, *, category_id: str | None = None) -> list[ExpertMarketExpert]:
        where = ["e.status = 'published'", "e.id <> ?"]
        params: list[Any] = [SYSTEM_DEFAULT_EXPERT_ID]
        if category_id:
            where.append("e.category_id = ?")
            params.append(category_id)
        rows = fetch_all(
            self.connection,
            f"""
            select
              e.id,
              e.name,
              e.category_id,
              c.name as category_name,
              e.ability_intro,
              e.localized_content,
              e.tags,
              e.market_labels,
              e.guide_questions,
              e.summon_button_text
            from experts e
            inner join expert_categories c on c.id = e.category_id
            where {' and '.join(where)}
            order by e.created_at desc, e.id asc
            """,
            params,
        )
        return [_map_market_expert(row) for row in rows]

    def get_market(self, expert_id: str) -> ExpertMarketExpert | None:
        row = fetch_one(
            self.connection,
            """
            select
              e.id,
              e.name,
              e.category_id,
              c.name as category_name,
              e.ability_intro,
              e.localized_content,
              e.tags,
              e.market_labels,
              e.guide_questions,
              e.summon_button_text
            from experts e
            inner join expert_categories c on c.id = e.category_id
            where e.id = ? and e.status = 'published' and e.id <> ?
            limit 1
            """,
            (expert_id, SYSTEM_DEFAULT_EXPERT_ID),
        )
        return _map_market_expert(row) if row else None

    def status_counts(self) -> dict[str, int]:
        rows = fetch_all(
            self.connection,
            """
            select status, count(*) as count
            from experts
            group by status
            """,
        )
        return {str(row["status"]): int(row["count"]) for row in rows}

    def category_exists(self, category_id: str) -> bool:
        row = fetch_one(
            self.connection,
            "select id from expert_categories where id = ? limit 1",
            (category_id,),
        )
        return row is not None

    def existing_skill_ids(self, skill_ids: list[str]) -> set[str]:
        if not skill_ids:
            return set()
        placeholders = ", ".join(["?"] * len(skill_ids))
        rows = fetch_all(
            self.connection,
            f"select id from skills where id in ({placeholders})",
            skill_ids,
        )
        return {str(row["id"]) for row in rows}

    def existing_knowledge_base_ids(self, knowledge_base_ids: list[str]) -> set[str]:
        if not knowledge_base_ids:
            return set()
        placeholders = ", ".join(["?"] * len(knowledge_base_ids))
        rows = fetch_all(
            self.connection,
            f"""
            select id from knowledge_bases
            where id in ({placeholders}) and deleted_at is null
            """,
            knowledge_base_ids,
        )
        return {str(row["id"]) for row in rows}

    def insert(
        self,
        *,
        expert_id: str,
        category_id: str,
        name: str,
        ability_intro: str,
        localized_content: dict[str, Any],
        tags: list[str],
        market_labels: list[str],
        status: str,
        guide_questions: list[str],
        summon_button_text: str | None,
        instructions: str,
        runtime_config: dict[str, Any],
        mcp_connector_ids: list[str],
        skill_runtime_targets: dict[str, list[str]],
    ) -> None:
        execute(
            self.connection,
            """
            insert into experts (
              id, category_id, name, ability_intro, localized_content, tags, market_labels, status,
              guide_questions, summon_button_text, instructions, runtime_config,
              mcp_connector_ids,
              skill_runtime_targets
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                expert_id,
                category_id,
                name,
                ability_intro,
                json_param(self.connection, localized_content),
                json_param(self.connection, tags),
                json_param(self.connection, market_labels),
                status,
                json_param(self.connection, guide_questions),
                summon_button_text,
                instructions,
                json_param(self.connection, runtime_config),
                json_param(self.connection, mcp_connector_ids),
                json_param(self.connection, skill_runtime_targets),
            ),
        )

    def update(
        self,
        expert_id: str,
        *,
        category_id: str,
        name: str,
        ability_intro: str,
        localized_content: dict[str, Any],
        tags: list[str],
        market_labels: list[str],
        guide_questions: list[str],
        summon_button_text: str | None,
        instructions: str,
        runtime_config: dict[str, Any],
        mcp_connector_ids: list[str],
        skill_runtime_targets: dict[str, list[str]],
    ) -> None:
        execute(
            self.connection,
            """
            update experts
            set category_id = ?,
                name = ?,
                ability_intro = ?,
                localized_content = ?,
                tags = ?,
                market_labels = ?,
                guide_questions = ?,
                summon_button_text = ?,
                instructions = ?,
                runtime_config = ?,
                mcp_connector_ids = ?,
                skill_runtime_targets = ?,
                updated_at = CURRENT_TIMESTAMP
            where id = ?
            """,
            (
                category_id,
                name,
                ability_intro,
                json_param(self.connection, localized_content),
                json_param(self.connection, tags),
                json_param(self.connection, market_labels),
                json_param(self.connection, guide_questions),
                summon_button_text,
                instructions,
                json_param(self.connection, runtime_config),
                json_param(self.connection, mcp_connector_ids),
                json_param(self.connection, skill_runtime_targets),
                expert_id,
            ),
        )

    def update_status(self, expert_id: str, status: str) -> None:
        execute(
            self.connection,
            """
            update experts
            set status = ?, updated_at = CURRENT_TIMESTAMP
            where id = ?
            """,
            (status, expert_id),
        )

    def delete(self, expert_id: str) -> int:
        # expert_skills / expert_knowledge_bases rows are removed by ON DELETE CASCADE
        # (foreign keys are enforced on both SQLite and PostgreSQL).
        cursor = execute(self.connection, "delete from experts where id = ?", (expert_id,))
        return rowcount(cursor)

    def has_active_chat_sessions(self, expert_id: str) -> bool:
        return (
            fetch_one(
                self.connection,
                """
                select id from chat_sessions
                where expert_id = ? and deleted_at is null
                limit 1
                """,
                (expert_id,),
            )
            is not None
        )

    def detach_deleted_chat_history(self, expert_id: str) -> None:
        # Deleted sessions and turns remain as durable product history. Clear only their live
        # Expert foreign key before deleting the Expert row.
        execute(
            self.connection,
            """
            update chat_turns
            set expert_id = null
            where expert_id = ?
              and session_id in (
                select id from chat_sessions where deleted_at is not null
              )
            """,
            (expert_id,),
        )

        execute(
            self.connection,
            """
            update chat_sessions
            set expert_id = null
            where expert_id = ? and deleted_at is not null
            """,
            (expert_id,),
        )

    def active_chat_session_ids(self, expert_id: str) -> list[str]:
        rows = fetch_all(
            self.connection,
            """
            select id from chat_sessions
            where expert_id = ? and deleted_at is null
            order by id
            """,
            (expert_id,),
        )
        return [str(row["id"]) for row in rows]

    def replace_skills(self, expert_id: str, skill_ids: list[str]) -> None:
        execute(self.connection, "delete from expert_skills where expert_id = ?", (expert_id,))
        for skill_id in skill_ids:
            execute(
                self.connection,
                "insert into expert_skills (id, expert_id, skill_id) values (?, ?, ?)",
                (f"expert_skill_{uuid4().hex}", expert_id, skill_id),
            )

    def replace_knowledge_bases(self, expert_id: str, knowledge_base_ids: list[str]) -> None:
        execute(
            self.connection,
            "delete from expert_knowledge_bases where expert_id = ?",
            (expert_id,),
        )
        for knowledge_base_id in knowledge_base_ids:
            execute(
                self.connection,
                """
                insert into expert_knowledge_bases (id, expert_id, knowledge_base_id)
                values (?, ?, ?)
                """,
                (f"expert_kb_{uuid4().hex}", expert_id, knowledge_base_id),
            )

    def skill_sources(self, skill_ids: list[str]) -> list[dict[str, Any]]:
        if not skill_ids:
            return []
        placeholders = ", ".join("?" for _ in skill_ids)
        rows = fetch_all(
            self.connection,
            f"""
            select id, slug, name, description, version, file_paths
            from skills where id in ({placeholders})
            """,
            skill_ids,
        )
        by_id = {str(row["id"]): row for row in rows}
        return [by_id[skill_id] for skill_id in skill_ids if skill_id in by_id]

    def _map_experts(self, rows: list[dict[str, Any]]) -> list[Expert]:
        expert_ids = [str(row["id"]) for row in rows]
        # Batch-fetch links once for the whole page to avoid an N+1 query per expert.
        skills_by_expert = self._skill_ids_by_expert(expert_ids)
        kbs_by_expert = self._knowledge_base_ids_by_expert(expert_ids)
        experts = []
        for row in rows:
            expert_id = str(row["id"])
            experts.append(
                Expert(
                    id=expert_id,
                    name=str(row["name"]),
                    categoryId=str(row["category_id"]),
                    categoryName=str(row["category_name"]),
                    abilityIntro=str(row["ability_intro"]),
                    localizedContent=_json_object(row["localized_content"]),
                    instructions=str(row["instructions"] or ""),
                    runtimeConfig=_json_object(row["runtime_config"]),
                    mcpConnectorIds=_json_string_list(row["mcp_connector_ids"]),
                    skillRuntimeTargets=_json_string_list_map(row["skill_runtime_targets"]),
                    tags=_json_string_list(row["tags"]),
                    marketLabels=_json_string_list(row["market_labels"]),
                    status=str(row["status"]),
                    skillIds=skills_by_expert.get(expert_id, []),
                    knowledgeBaseIds=kbs_by_expert.get(expert_id, []),
                    guideQuestions=_json_string_list(row["guide_questions"]),
                    summonButtonText=(
                        str(row["summon_button_text"])
                        if row["summon_button_text"] is not None
                        else None
                    ),
                    createdAt=str(row["created_at"]),
                    updatedAt=str(row["updated_at"]),
                )
            )
        return experts

    def _skill_ids_by_expert(self, expert_ids: list[str]) -> dict[str, list[str]]:
        if not expert_ids:
            return {}
        placeholders = ", ".join(["?"] * len(expert_ids))
        rows = fetch_all(
            self.connection,
            f"""
            select expert_id, skill_id from expert_skills
            where expert_id in ({placeholders})
            order by expert_id, created_at asc, skill_id asc
            """,
            expert_ids,
        )
        grouped: dict[str, list[str]] = {}
        for row in rows:
            grouped.setdefault(str(row["expert_id"]), []).append(str(row["skill_id"]))
        return grouped

    def _knowledge_base_ids_by_expert(self, expert_ids: list[str]) -> dict[str, list[str]]:
        if not expert_ids:
            return {}
        placeholders = ", ".join(["?"] * len(expert_ids))
        # Knowledge bases are soft-deleted (deleted_at), so the join-table ON DELETE CASCADE only
        # fires at GC purge time. Filter deleted_at here so a soft-deleted KB never lingers in an
        # expert's knowledgeBaseIds.
        rows = fetch_all(
            self.connection,
            f"""
            select ekb.expert_id, kb.id as knowledge_base_id
            from expert_knowledge_bases ekb
            inner join knowledge_bases kb on kb.id = ekb.knowledge_base_id
            where ekb.expert_id in ({placeholders}) and kb.deleted_at is null
            order by ekb.expert_id, ekb.created_at asc, kb.id asc
            """,
            expert_ids,
        )
        grouped: dict[str, list[str]] = {}
        for row in rows:
            grouped.setdefault(str(row["expert_id"]), []).append(str(row["knowledge_base_id"]))
        return grouped


_EXPERT_SELECT = """
select
  e.id,
  e.name,
  e.category_id,
  c.name as category_name,
  e.ability_intro,
  e.localized_content,
  e.tags,
  e.market_labels,
  e.status,
  e.guide_questions,
  e.summon_button_text,
  e.instructions,
  e.runtime_config,
  e.mcp_connector_ids,
  e.skill_runtime_targets,
  e.created_at,
  e.updated_at
from experts e
inner join expert_categories c on c.id = e.category_id
"""


def _json_string_list(value: Any) -> list[str]:
    # jsonb columns come back as a list on PostgreSQL and as a JSON text on SQLite.
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str)]
    return []


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    return dict(value) if isinstance(value, dict) else {}


def _json_string_list_map(value: Any) -> dict[str, list[str]]:
    result = {}
    for key, item in _json_object(value).items():
        if isinstance(item, list):
            result[str(key)] = [str(entry) for entry in item if isinstance(entry, str)]
    return result


def _map_market_expert(row: dict[str, Any]) -> ExpertMarketExpert:
    return ExpertMarketExpert(
        id=str(row["id"]),
        name=str(row["name"]),
        categoryId=str(row["category_id"]),
        categoryName=str(row["category_name"]),
        abilityIntro=str(row["ability_intro"]),
        localizedContent=_json_object(row["localized_content"]),
        tags=_json_string_list(row["tags"]),
        marketLabels=_json_string_list(row["market_labels"]),
        guideQuestions=_json_string_list(row["guide_questions"]),
        summonButtonText=(
            str(row["summon_button_text"])
            if row["summon_button_text"] is not None
            else None
        ),
        isAccessible=False,
    )
