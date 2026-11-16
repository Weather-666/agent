from __future__ import annotations

import secrets

from app.core.errors import ApiError
from app.db import DatabaseConnection
from app.domain.audit import AuditCategory, AuditOperationType, AuditResource
from app.domain.auth import Principal
from app.domain.experts import (
    CreateExpertRequest,
    Expert,
    ExpertMarketExpert,
    ExpertStatsResponse,
    LocalizedExpertContent,
    UpdateExpertRequest,
)
from app.services.audit_service import AuditService, changes
from app.services.expert_repository import ExpertRepository


class ExpertService:
    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection
        self.repo = ExpertRepository(connection)

    def list(
        self,
        *,
        name: str | None = None,
        category_id: str | None = None,
        status: str | None = None,
    ) -> list[Expert]:
        return self.repo.list(name=name, category_id=category_id, status=status)

    def stats(self) -> ExpertStatsResponse:
        counts = self.repo.status_counts()
        return ExpertStatsResponse(
            total=sum(counts.values()),
            published=counts.get("published", 0),
            draft=counts.get("draft", 0),
            unlisted=counts.get("unlisted", 0),
        )

    def list_market_experts(self, *, category_id: str | None = None) -> list[ExpertMarketExpert]:
        return self.repo.list_market(category_id=category_id)

    def get_market_expert(self, expert_id: str) -> ExpertMarketExpert:
        expert = self.repo.get_market(expert_id)
        if not expert:
            raise ApiError(404, "EXPERT_NOT_FOUND", "Expert not found")
        return expert

    def get(self, expert_id: str) -> Expert:
        expert = self.repo.get(expert_id)
        if not expert:
            raise ApiError(404, "EXPERT_NOT_FOUND", "Expert not found")
        return expert

    def create(
        self,
        principal: Principal,
        request: CreateExpertRequest,
        *,
        request_id: str,
    ) -> Expert:
        skill_ids = _unique_strings(request.skillIds)
        knowledge_base_ids = _unique_strings(request.knowledgeBaseIds)
        self._require_category(request.categoryId)
        self._require_skills(skill_ids)
        self._require_knowledge_bases(knowledge_base_ids)
        expert_id = self._new_unique_expert_id()
        skill_runtime_targets = _skill_runtime_targets(
            request.skillRuntimeTargets, skill_ids
        )
        mcp_connector_ids = _mcp_connector_ids(request.mcpConnectorIds)
        self.repo.insert(
            expert_id=expert_id,
            category_id=request.categoryId,
            name=request.name,
            ability_intro=request.abilityIntro,
            localized_content=_localized_expert_content(request.localizedContent),
            tags=_unique_strings(request.tags),
            market_labels=_unique_strings(request.marketLabels),
            status="draft",
            guide_questions=_unique_strings(request.guideQuestions),
            summon_button_text=request.summonButtonText,
            instructions=request.instructions,
            runtime_config={
                runtime: config.model_dump()
                for runtime, config in request.runtimeConfig.items()
            },
            mcp_connector_ids=mcp_connector_ids,
            skill_runtime_targets=skill_runtime_targets,
        )
        self.repo.replace_skills(expert_id, skill_ids)
        self.repo.replace_knowledge_bases(expert_id, knowledge_base_ids)
        audit = AuditService(self.connection)
        audit.record(
            audit.context(principal, request_id),
            category=AuditCategory.EXPERT,
            action="expert.create",
            operation_type=AuditOperationType.CREATE,
            resource=AuditResource(type="expert", id=expert_id, name=request.name),
            metadata={
                "categoryId": request.categoryId,
                "status": "draft",
                "skillIds": skill_ids,
                "knowledgeBaseIds": knowledge_base_ids,
                "tags": _unique_strings(request.tags),
                "marketLabels": _unique_strings(request.marketLabels),
                "runtimeTypes": sorted(
                    runtime
                    for runtime, config in request.runtimeConfig.items()
                    if config.enabled
                ),
            },
        )
        self.connection.commit()
        return self.get(expert_id)

    def update(
        self,
        principal: Principal,
        expert_id: str,
        request: UpdateExpertRequest,
        *,
        request_id: str,
    ) -> Expert:
        current = self.get(expert_id)
        if current.status == "published":
            raise ApiError(
                409,
                "EXPERT_PUBLISHED_READ_ONLY",
                "Published Experts must be unlisted before they can be modified",
            )
        next_category_id = (
            request.categoryId if request.categoryId is not None else current.categoryId
        )
        self._require_category(next_category_id)

        skill_ids = _unique_strings(request.skillIds) if request.skillIds is not None else None
        knowledge_base_ids = (
            _unique_strings(request.knowledgeBaseIds)
            if request.knowledgeBaseIds is not None
            else None
        )
        if skill_ids is not None:
            self._require_skills(skill_ids)
        if knowledge_base_ids is not None:
            self._require_knowledge_bases(knowledge_base_ids)
        next_skill_ids = skill_ids if skill_ids is not None else current.skillIds
        next_skill_runtime_targets = (
            _skill_runtime_targets(request.skillRuntimeTargets, next_skill_ids)
            if request.skillRuntimeTargets is not None
            else {
                skill_id: runtimes
                for skill_id, runtimes in current.skillRuntimeTargets.items()
                if skill_id in next_skill_ids
            }
        )
        next_mcp_connector_ids = (
            _mcp_connector_ids(request.mcpConnectorIds)
            if request.mcpConnectorIds is not None
            else current.mcpConnectorIds
        )

        self.repo.update(
            expert_id,
            category_id=next_category_id,
            name=request.name if request.name is not None else current.name,
            ability_intro=(
                request.abilityIntro if request.abilityIntro is not None else current.abilityIntro
            ),
            localized_content=(
                _localized_expert_content(request.localizedContent)
                if request.localizedContent is not None
                else _localized_expert_content(current.localizedContent)
            ),
            tags=_unique_strings(request.tags) if request.tags is not None else current.tags,
            market_labels=(
                _unique_strings(request.marketLabels)
                if request.marketLabels is not None
                else current.marketLabels
            ),
            guide_questions=(
                _unique_strings(request.guideQuestions)
                if request.guideQuestions is not None
                else current.guideQuestions
            ),
            summon_button_text=(
                request.summonButtonText
                if request.summonButtonText is not None
                else current.summonButtonText
            ),
            instructions=(
                request.instructions
                if request.instructions is not None
                else current.instructions
            ),
            runtime_config={
                runtime: config.model_dump()
                for runtime, config in (
                    request.runtimeConfig
                    if request.runtimeConfig is not None
                    else current.runtimeConfig
                ).items()
            },
            mcp_connector_ids=next_mcp_connector_ids,
            skill_runtime_targets=next_skill_runtime_targets,
        )
        if skill_ids is not None:
            self.repo.replace_skills(expert_id, skill_ids)
        if knowledge_base_ids is not None:
            self.repo.replace_knowledge_bases(expert_id, knowledge_base_ids)
        updated = self.get(expert_id)
        event_changes = changes(
            _expert_audit_state(current),
            _expert_audit_state(updated),
            {
                "name",
                "categoryId",
                "abilityIntro",
                "localizedContent",
                "tags",
                "marketLabels",
                "skillIds",
                "knowledgeBaseIds",
                "guideQuestions",
                "summonButtonText",
                "instructions",
                "runtimeConfig",
                "mcpConnectorIds",
                "skillRuntimeTargets",
            },
        )
        if event_changes:
            audit = AuditService(self.connection)
            audit.record(
                audit.context(principal, request_id),
                category=AuditCategory.EXPERT,
                action="expert.update",
                operation_type=AuditOperationType.UPDATE,
                resource=AuditResource(type="expert", id=updated.id, name=updated.name),
                changes=event_changes,
            )
        self.connection.commit()
        return updated

    def update_status(
        self,
        principal: Principal,
        expert_id: str,
        status: str,
        *,
        request_id: str,
    ) -> Expert:
        current = self.get(expert_id)
        self.repo.update_status(expert_id, status)
        updated = self.get(expert_id)
        event_changes = changes(
            {"status": current.status}, {"status": updated.status}, {"status"}
        )
        if event_changes:
            audit = AuditService(self.connection)
            audit.record(
                audit.context(principal, request_id),
                category=AuditCategory.EXPERT,
                action="expert.status_change",
                operation_type=AuditOperationType.UPDATE,
                resource=AuditResource(type="expert", id=current.id, name=current.name),
                changes=event_changes,
            )
        self.connection.commit()
        return updated

    def delete(
        self,
        principal: Principal,
        expert_id: str,
        *,
        request_id: str,
    ) -> None:
        current = self.get(expert_id)
        if self.repo.has_active_chat_sessions(expert_id):
            raise ApiError(
                409,
                "EXPERT_IN_USE",
                "Expert is referenced by an active Chat Session",
            )
        self.repo.detach_deleted_chat_history(expert_id)
        if self.repo.delete(expert_id) <= 0:
            raise ApiError(404, "EXPERT_NOT_FOUND", "Expert not found")
        audit = AuditService(self.connection)
        audit.record(
            audit.context(principal, request_id),
            category=AuditCategory.EXPERT,
            action="expert.delete",
            operation_type=AuditOperationType.DELETE,
            resource=AuditResource(type="expert", id=current.id, name=current.name),
            metadata={
                "categoryId": current.categoryId,
                "status": current.status,
                "skillIds": current.skillIds,
                "knowledgeBaseIds": current.knowledgeBaseIds,
            },
        )
        self.connection.commit()

    def _require_category(self, category_id: str) -> None:
        if not self.repo.category_exists(category_id):
            raise ApiError(404, "EXPERT_CATEGORY_NOT_FOUND", "Expert category not found")

    def _require_skills(self, skill_ids: list[str]) -> None:
        existing = self.repo.existing_skill_ids(skill_ids)
        missing = [skill_id for skill_id in skill_ids if skill_id not in existing]
        if missing:
            raise ApiError(404, "SKILL_NOT_FOUND", "Skill not found", {"skillIds": missing})

    def _require_knowledge_bases(self, knowledge_base_ids: list[str]) -> None:
        if len(knowledge_base_ids) > 1:
            raise ApiError(
                400,
                "KB_LIMIT_EXCEEDED",
                "Each expert can only bind one knowledge base",
                {"knowledgeBaseIds": knowledge_base_ids},
            )

        existing = self.repo.existing_knowledge_base_ids(knowledge_base_ids)
        missing = [kb_id for kb_id in knowledge_base_ids if kb_id not in existing]
        if missing:
            raise ApiError(
                404,
                "KB_NOT_FOUND",
                "Knowledge base not found",
                {"knowledgeBaseIds": missing},
            )

    def _new_unique_expert_id(self) -> str:
        for _ in range(8):
            expert_id = secrets.token_hex(8)
            if not self.repo.expert_id_exists(expert_id):
                return expert_id
        raise ApiError(
            503,
            "EXPERT_ID_GENERATION_FAILED",
            "Could not allocate a unique Expert identity",
        )


def _unique_strings(values: list[str]) -> list[str]:
    return [value for value in dict.fromkeys(values) if value]


def _expert_audit_state(expert: Expert) -> dict[str, object]:
    return {
        "name": expert.name,
        "categoryId": expert.categoryId,
        "abilityIntro": expert.abilityIntro,
        "localizedContent": _localized_expert_content(expert.localizedContent),
        "tags": expert.tags,
        "marketLabels": expert.marketLabels,
        "skillIds": expert.skillIds,
        "knowledgeBaseIds": expert.knowledgeBaseIds,
        "guideQuestions": expert.guideQuestions,
        "summonButtonText": expert.summonButtonText,
        "instructions": expert.instructions,
        "runtimeConfig": {
            runtime: config.model_dump()
            for runtime, config in expert.runtimeConfig.items()
        },
        "mcpConnectorIds": expert.mcpConnectorIds,
        "skillRuntimeTargets": expert.skillRuntimeTargets,
    }


def _localized_expert_content(
    value: dict[str, LocalizedExpertContent],
) -> dict[str, dict[str, str | None]]:
    return {
        locale: content.model_dump(exclude_none=True)
        for locale, content in value.items()
    }


def _skill_runtime_targets(
    value: dict[str, list[str]],
    skill_ids: list[str],
) -> dict[str, list[str]]:
    unknown = sorted(set(value) - set(skill_ids))
    if unknown:
        raise ApiError(
            400,
            "EXPERT_SKILL_RUNTIME_INVALID",
            "skillRuntimeTargets references an unbound Skill",
            {"skillIds": unknown},
        )
    result = {}
    for skill_id, runtimes in value.items():
        unique = _unique_strings(runtimes)
        if any(runtime not in {"codex", "opencode"} for runtime in unique):
            raise ApiError(
                400,
                "EXPERT_SKILL_RUNTIME_INVALID",
                "skillRuntimeTargets contains an unsupported runtime",
                {"skillId": skill_id},
            )
        if not unique:
            raise ApiError(
                400,
                "EXPERT_SKILL_RUNTIME_INVALID",
                "A bound Skill runtime list cannot be empty",
                {"skillId": skill_id},
            )
        result[skill_id] = unique
    return result


def _mcp_connector_ids(values: list[str]) -> list[str]:
    if any(not value.strip() for value in values):
        raise ApiError(
            400,
            "EXPERT_MCP_CONNECTOR_ID_INVALID",
            "MCP Connector ids must be non-empty strings",
        )
    if len(set(values)) != len(values):
        raise ApiError(
            400,
            "EXPERT_MCP_CONNECTOR_DUPLICATE",
            "MCP Connector ids must be unique",
        )
    return list(values)
