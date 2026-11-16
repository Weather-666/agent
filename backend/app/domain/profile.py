from typing import Literal
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator


PreferredLocale = Literal["zh-CN", "en-US"]


class CurrentUserProfile(BaseModel):
    id: str
    email: str
    name: str
    preferredLocale: PreferredLocale | None = None
    avatarUrl: str | None = None
    avatarUrlExpiresAt: str | None = None
    updatedAt: str


class UpdateCurrentUserProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    preferredLocale: PreferredLocale | None = None

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, value: object) -> object:
        if value is None:
            raise ValueError("Name cannot be null")
        if not isinstance(value, str):
            return value
        if any(unicodedata.category(character) == "Cc" for character in value):
            raise ValueError("Name cannot contain control characters")
        stripped = value.strip()
        if not stripped:
            raise ValueError("Name cannot be empty")
        return stripped
