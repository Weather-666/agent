from typing import Literal

from pydantic import BaseModel, Field

from app.domain.experts import ExpertRuntimeType

ChatSessionStatus = Literal["active", "archived"]
ChatSearchScope = Literal["all", "question", "answer"]
ChatSearchMatchedType = Literal["title", "question", "answer"]


class CreateSessionRequest(BaseModel):
    title: str | None = None
    expertId: str | None = None
    runtimeType: ExpertRuntimeType | None = None


class ChatTurnRequest(BaseModel):
    # The public turn payload is intentionally narrow. Do not re-add model / retrieval options
    # without wiring them into the outgoing ACP payload, or callers will think they take effect.
    question: str
    webSearchEnabled: bool | None = Field(
        default=None,
        description=(
            "Routes ACP turns to the search prefix with search_mode=auto when true; "
            "otherwise uses the default prefix with search_mode=off."
        ),
    )
    attachmentFileIds: list[str] | None = Field(
        default=None,
        description=(
            "Completed library_files ids referenced by this turn (docs/LIBRARY_FILE_LIFECYCLE.md "
            "§7.3). Each is authorized per §5; a temporary file must belong to this session and not "
            "be expired."
        ),
    )


class RenameSessionRequest(BaseModel):
    title: str


class PinSessionRequest(BaseModel):
    isPinned: bool = True


class ArchiveSessionRequest(BaseModel):
    archived: bool = True


class ResolvePermissionRequest(BaseModel):
    # One of outcome/optionId is required.
    outcome: str | None = None
    optionId: str | None = None


class ChatSession(BaseModel):
    id: str
    title: str | None = None
    status: ChatSessionStatus = "active"
    isPinned: bool = False
    expertId: str | None = None
    runtimeType: ExpertRuntimeType | None = None
    createdAt: str
    updatedAt: str


class ChatTurn(BaseModel):
    id: str
    sessionId: str
    requestText: str
    reasoningText: str | None = None
    responseText: str | None = None
    eventSeq: int = 0
    model: str | None = None
    expertId: str | None = None
    runtimeType: ExpertRuntimeType | None = None
    status: str
    stopReason: str | None = None
    errorMessage: str | None = None
    # Per-turn attachment provenance snapshot (docs/LIBRARY_FILE_LIFECYCLE.md §9). Self-contained,
    # so it survives the referenced file being expired and GC-removed.
    attachments: list[dict] = Field(default_factory=list)
    # Internal LightRAG retrieval provenance snapshot. Services must project this through
    # ChatRetrievalSource before returning it to a caller; the stored shape intentionally keeps
    # integrity identities that are not part of the public display contract.
    retrievalRefs: list[dict] = Field(default_factory=list)
    createdAt: str
    completedAt: str | None = None


class ChatRetrievalSource(BaseModel):
    """Caller-safe source metadata projected from an authorized retrieval snapshot."""

    citationId: str | None = None
    citationIds: list[str] = Field(default_factory=list)
    knowledgeBaseId: str | None = None
    knowledgeBaseName: str | None = None
    documentId: str | None = None
    fileName: str
    pageNumber: int | None = Field(default=None, ge=1)
    mimeType: str | None = None
    hitText: str | None = None
    locator: dict = Field(default_factory=dict)
    previewUrl: str | None = None
    downloadUrl: str | None = None
    available: bool = True


class ChatTurnResponse(ChatTurn):
    """Public Turn shape with display-safe retrieval sources."""

    retrievalRefs: list[ChatRetrievalSource] = Field(default_factory=list)


class ChatMessagesResponse(BaseModel):
    items: list[ChatTurnResponse] = Field(default_factory=list)


class CitationPreviewResponse(BaseModel):
    citationId: str
    knowledgeBaseId: str
    knowledgeBaseName: str
    documentId: str
    fileName: str
    pageNumber: int | None = Field(default=None, ge=1)
    hitText: str
    locator: dict = Field(default_factory=dict)
    previewType: Literal["text", "url", "unsupported"]
    content: str | None = None
    url: str | None = None
    mimeType: str | None = None
    expiresAt: str | None = None


class CitationDownloadResponse(BaseModel):
    citationId: str
    fileName: str
    downloadUrl: str
    expiresAt: str


class ChatSearchItem(BaseModel):
    sessionId: str
    title: str | None = None
    matchedTurnId: str
    matchedType: ChatSearchMatchedType
    snippet: str


class ChatSearchResponse(BaseModel):
    items: list[ChatSearchItem]
    total: int
    limit: int
    offset: int
