from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

FeaturedCategoryTone = Literal["blue", "green", "violet", "orange"]
FeaturedExampleStatus = Literal["pending", "live", "rejected", "reviewing", "unlisted"]
FeaturedReviewState = Literal["none", "normal", "expiring", "expired"]
CategoryName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _review_cycle(value: object) -> object:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("Review cycle must be an integer number of days")
    return value


ReviewCycleDays = Annotated[Literal[30, 60, 90], BeforeValidator(_review_cycle)]


class CreateFeaturedCategoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: CategoryName
    tone: FeaturedCategoryTone


class UpdateFeaturedCategoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: CategoryName | None = None
    tone: FeaturedCategoryTone | None = None

    @field_validator("name", "tone", mode="before")
    @classmethod
    def reject_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("Field cannot be null")
        return value


class FeaturedOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[Identifier]


class CreateFeaturedExampleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    categoryId: Identifier
    question: Question
    reviewCycleDays: ReviewCycleDays | None = None


class UpdateFeaturedExampleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    categoryId: Identifier | None = None
    question: Question | None = None
    reviewCycleDays: ReviewCycleDays | None = None

    @field_validator("categoryId", "question", mode="before")
    @classmethod
    def reject_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("Field cannot be null")
        return value


class ReviewFeaturedExampleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    expectedUpdatedAt: AwareDatetime
    reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ] | None = None

    @model_validator(mode="after")
    def require_rejection_reason(self) -> "ReviewFeaturedExampleRequest":
        if self.decision == "reject" and self.reason is None:
            raise ValueError("A rejection reason is required")
        return self


class FeaturedCategory(BaseModel):
    id: str
    name: str
    short: str
    tone: FeaturedCategoryTone
    sortOrder: int
    createdAt: str
    updatedAt: str


class FeaturedCategoryListResponse(BaseModel):
    items: list[FeaturedCategory]


class FeaturedExample(BaseModel):
    id: str
    categoryId: str
    question: str
    sortOrder: int
    status: FeaturedExampleStatus
    reviewCycleDays: ReviewCycleDays | None
    reviewState: FeaturedReviewState
    reviewedAt: str | None
    expiresAt: str | None
    rejectReason: str | None
    clickCount: int = Field(ge=0)
    createdBy: str | None
    authorName: str | None
    updatedBy: str | None
    reviewedBy: str | None
    createdAt: str
    updatedAt: str


class FeaturedExampleCounts(BaseModel):
    total: int
    live: int
    pending: int
    reviewing: int
    rejected: int
    unlisted: int
    expiring: int
    expired: int


class FeaturedExampleListResponse(BaseModel):
    items: list[FeaturedExample]
    counts: FeaturedExampleCounts


class FeaturedExampleOrderResponse(BaseModel):
    items: list[FeaturedExample]


class FeaturedMarketExample(BaseModel):
    id: str
    question: str
    categoryId: str
    categoryName: str
    categoryTone: FeaturedCategoryTone
    sortOrder: int
    clickCount: int = Field(ge=0)


class FeaturedMarketExampleListResponse(BaseModel):
    items: list[FeaturedMarketExample]


class FeaturedExampleUseResponse(BaseModel):
    id: str
    question: str
    clickCount: int = Field(ge=0)
