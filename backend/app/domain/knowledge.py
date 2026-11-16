from typing import Any, Literal

from pydantic import BaseModel, Field


# Product lifecycle and index provisioning are separate state machines. An active KB can be
# provisioning or failed without ever falling back to another KB's index.
KbStatus = Literal["active", "archived"]
KbIndexStatus = Literal["provisioning", "ready", "failed", "deleting"]
FileType = Literal["pdf", "docx", "pptx", "xlsx", "md", "txt", "html", "csv", "json"]
ParseStatus = Literal["pending", "processing", "ready", "failed"]
IndexStatus = Literal["pending", "processing", "ready", "failed", "stale"]


# Knowledge bases -----------------------------------------------------------------


class CreateKnowledgeBaseRequest(BaseModel):
    name: str
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateKnowledgeBaseRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None


class KnowledgeBase(BaseModel):
    id: str
    # Creator attribution only. Access is governed by platform permissions, not ownership.
    ownerUserId: str | None = None
    ownerUserName: str | None = None
    name: str
    description: str | None = None
    status: KbStatus
    indexStatus: KbIndexStatus = "provisioning"
    indexError: str | None = None
    indexWorkspace: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    createdAt: str
    updatedAt: str


class KnowledgeBaseListResponse(BaseModel):
    items: list[KnowledgeBase]


# Documents -----------------------------------------------------------------------


class Document(BaseModel):
    id: str
    knowledgeBaseId: str
    fileName: str
    fileType: FileType
    mimeType: str | None = None
    fileSizeBytes: int
    storageKey: str
    contentHash: str | None = None
    sourceSha: str | None = None
    indexedSha: str | None = None
    indexDocumentId: str | None = None
    indexPipelineVersion: str | None = None
    parseStatus: ParseStatus
    indexStatus: IndexStatus
    parseError: str | None = None
    lastError: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    createdAt: str
    updatedAt: str


class DocumentListResponse(BaseModel):
    items: list[Document]


class UpdateDocumentRequest(BaseModel):
    fileName: str | None = None
    metadata: dict[str, Any] | None = None


# Upload flow ---------------------------------------------------------------------


class UploadUrlRequest(BaseModel):
    fileName: str
    mimeType: str | None = None
    fileSizeBytes: int
    contentHash: str | None = None


class UploadUrlResponse(BaseModel):
    uploadSessionId: str
    documentId: str
    method: Literal["PUT"] = "PUT"
    uploadUrl: str
    headers: dict[str, str] = Field(default_factory=dict)
    objectKey: str
    expiresAt: str


# Batch upload endpoints are deliberately non-atomic: each file is processed independently and
# the response reports every item's outcome, so one bad file never aborts the others and the
# caller can retry only the failures. `error` mirrors the ApiError envelope (code/message/details).
class BatchItemError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class UploadUrlsRequest(BaseModel):
    files: list[UploadUrlRequest] = Field(min_length=1, max_length=50)


class UploadUrlResult(BaseModel):
    fileName: str
    status: Literal["created", "failed"]
    upload: UploadUrlResponse | None = None
    error: BatchItemError | None = None


class UploadUrlsResponse(BaseModel):
    items: list[UploadUrlResult]


class CompleteUploadRequest(BaseModel):
    uploadSessionId: str
    etag: str | None = None
    fileSizeBytes: int | None = None


class CompleteUploadsRequest(BaseModel):
    items: list[CompleteUploadRequest] = Field(min_length=1, max_length=50)


class CompleteUploadResult(BaseModel):
    uploadSessionId: str
    status: Literal["completed", "failed"]
    document: Document | None = None
    error: BatchItemError | None = None


class CompleteUploadsResponse(BaseModel):
    items: list[CompleteUploadResult]


class DownloadUrlResponse(BaseModel):
    method: Literal["GET"] = "GET"
    downloadUrl: str
    expiresAt: str


# Index approval ------------------------------------------------------------------


IndexReviewStatus = Literal["not_required", "pending_parse", "review_required", "approved"]


class IndexReviewDocument(BaseModel):
    documentId: str
    fileName: str
    fileSizeBytes: int


class IndexReview(BaseModel):
    knowledgeBaseId: str
    status: IndexReviewStatus
    thresholdBytes: int
    documentCount: int = 0
    totalSizeBytes: int = 0
    batchToken: str | None = None
    documents: list[IndexReviewDocument] = Field(default_factory=list)


class ApproveIndexRequest(BaseModel):
    batchToken: str = Field(min_length=1, max_length=128)
