import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SYSTEM_DEFAULT_EXPERT_ID = "1825107e997dfde2"

ExpertStatus = Literal["published", "draft", "unlisted"]
ExpertMarketLabel = Literal["hot"]
ExpertRuntimeType = Literal["codex", "opencode"]


class SecretReference(BaseModel):
    secretRef: str = Field(pattern=r"^[A-Z_][A-Z0-9_]*$")


class ExpertRuntimeTarget(BaseModel):
    enabled: bool = False
    model: str = "gpt-5.5"
    maxInstances: int = Field(default=50, ge=1, le=100)
    idleTtlSeconds: int = Field(default=900, ge=1)
    turnTimeoutSeconds: int = Field(default=900, ge=1)
    permissionMode: Literal["deny", "auto_approve", "interactive"] = "auto_approve"
    requireVirtualKey: bool = True
    environment: dict[str, SecretReference] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_runtime(self) -> "ExpertRuntimeTarget":
        if self.enabled and not self.model.strip():
            raise ValueError("Enabled Runtime model must be a non-empty string")
        if any(
            not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name)
            for name in self.environment
        ):
            raise ValueError("Runtime environment names must use uppercase shell syntax")
        return self


class LocalizedExpertContent(BaseModel):
    name: str | None = None
    abilityIntro: str | None = None
    categoryName: str | None = None
    summonButtonText: str | None = None


def default_runtime_config() -> dict[ExpertRuntimeType, ExpertRuntimeTarget]:
    return {
        "codex": ExpertRuntimeTarget(enabled=True),
        "opencode": ExpertRuntimeTarget(enabled=False),
    }

class ExpertCategory(BaseModel):
    id: str
    name: str
    description: str | None = None
    createdAt: str
    updatedAt: str


class CreateExpertCategoryRequest(BaseModel):
    name: str
    description: str | None = None


class UpdateExpertCategoryRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class ExpertCategoryListResponse(BaseModel):
    items: list[ExpertCategory]


class ExpertMarketCategory(BaseModel):
    id: str
    name: str
    description: str | None = None


class ExpertMarketCategoryListResponse(BaseModel):
    items: list[ExpertMarketCategory]


class Expert(BaseModel):
    id: str
    name: str
    categoryId: str
    categoryName: str
    abilityIntro: str
    localizedContent: dict[str, LocalizedExpertContent] = Field(default_factory=dict)
    instructions: str = ""
    runtimeConfig: dict[ExpertRuntimeType, ExpertRuntimeTarget] = Field(
        default_factory=default_runtime_config
    )
    mcpConnectorIds: list[str] = Field(default_factory=list)
    skillRuntimeTargets: dict[str, list[ExpertRuntimeType]] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    marketLabels: list[ExpertMarketLabel] = Field(default_factory=list)
    status: ExpertStatus
    skillIds: list[str] = Field(default_factory=list)
    knowledgeBaseIds: list[str] = Field(default_factory=list, max_length=1)
    guideQuestions: list[str] = Field(default_factory=list, max_length=3)
    summonButtonText: str | None = None
    createdAt: str
    updatedAt: str


class CreateExpertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    categoryId: str
    abilityIntro: str
    localizedContent: dict[str, LocalizedExpertContent] = Field(default_factory=dict)
    instructions: str = ""
    runtimeConfig: dict[ExpertRuntimeType, ExpertRuntimeTarget] = Field(
        default_factory=default_runtime_config
    )
    mcpConnectorIds: list[str] = Field(default_factory=list)
    skillRuntimeTargets: dict[str, list[ExpertRuntimeType]] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    marketLabels: list[ExpertMarketLabel] = Field(default_factory=list)
    skillIds: list[str] = Field(default_factory=list)
    knowledgeBaseIds: list[str] = Field(default_factory=list, max_length=1)
    guideQuestions: list[str] = Field(default_factory=list, max_length=3)
    summonButtonText: str | None = None


class UpdateExpertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    categoryId: str | None = None
    abilityIntro: str | None = None
    localizedContent: dict[str, LocalizedExpertContent] | None = None
    instructions: str | None = None
    runtimeConfig: dict[ExpertRuntimeType, ExpertRuntimeTarget] | None = None
    mcpConnectorIds: list[str] | None = None
    skillRuntimeTargets: dict[str, list[ExpertRuntimeType]] | None = None
    tags: list[str] | None = None
    marketLabels: list[ExpertMarketLabel] | None = None
    skillIds: list[str] | None = None
    knowledgeBaseIds: list[str] | None = Field(default=None, max_length=1)
    guideQuestions: list[str] | None = Field(default=None, max_length=3)
    summonButtonText: str | None = None


class UpdateExpertStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["published", "unlisted"]


class ExpertListResponse(BaseModel):
    items: list[Expert]


class ExpertMarketExpert(BaseModel):
    id: str
    name: str
    categoryId: str
    categoryName: str
    abilityIntro: str
    localizedContent: dict[str, LocalizedExpertContent] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    marketLabels: list[ExpertMarketLabel] = Field(default_factory=list)
    guideQuestions: list[str] = Field(default_factory=list, max_length=3)
    summonButtonText: str | None = None
    isAccessible: bool


class ExpertMarketExpertListResponse(BaseModel):
    items: list[ExpertMarketExpert]


class ExpertStatsResponse(BaseModel):
    total: int
    published: int
    draft: int
    unlisted: int
