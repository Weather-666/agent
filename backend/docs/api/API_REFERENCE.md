# Experts Backend API

Version: `0.1.0`

This document is generated from the FastAPI OpenAPI schema.

## audit-events

### GET `/api/v1/audit-events`

- Summary: List Audit Events

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| query | category | no | AuditCategory \| null | - |
| query | operationType | no | AuditOperationType \| null | - |
| query | actorId | no | string \| null | - |
| query | resourceType | no | string \| null | - |
| query | resourceId | no | string \| null | - |
| query | search | no | string \| null | - |
| query | from | no | string \| null | - |
| query | to | no | string \| null | - |
| query | page | no | integer | - |
| query | pageSize | no | integer | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | AuditEventListResponse |
| 422 | application/json | HTTPValidationError |

## auth

### POST `/api/v1/auth/login`

- Summary: Login

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| body | application/json | yes | LoginRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | object |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/auth/logout`

- Summary: Logout

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| body | application/json | yes | LogoutRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 204 | - | Successful Response |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/auth/me`

- Summary: Get Current Profile

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | CurrentUserProfile |
| 422 | application/json | HTTPValidationError |

### PATCH `/api/v1/auth/me`

- Summary: Update Current Profile

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | UpdateCurrentUserProfileRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | CurrentUserProfile |
| 422 | application/json | HTTPValidationError |

### DELETE `/api/v1/auth/me/avatar`

- Summary: Delete Current Avatar

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | CurrentUserProfile |
| 422 | application/json | HTTPValidationError |

### PUT `/api/v1/auth/me/avatar`

- Summary: Upload Current Avatar

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |
| body | multipart/form-data | yes | Body_upload_current_avatar_api_v1_auth_me_avatar_put | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | CurrentUserProfile |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/auth/password-reset/confirm`

- Summary: Confirm Password Reset

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| body | application/json | yes | PasswordResetConfirmRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | PasswordResetMessageResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/auth/password-reset/request`

- Summary: Request Password Reset

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| body | application/json | yes | PasswordResetRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 202 | application/json | PasswordResetMessageResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/auth/refresh`

- Summary: Refresh

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| body | application/json | yes | RefreshRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | object |
| 422 | application/json | HTTPValidationError |

## chat

### POST `/api/v1/chat/permissions/{permission_id}`

- Summary: Resolve Permission

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | permission_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | ResolvePermissionRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | object |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/chat/search`

- Summary: Search Chat Sessions

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| query | keyword | yes | string | Keyword trimmed and matched against chat questions and/or answers. |
| query | scope | no | string | - |
| query | limit | no | integer | - |
| query | offset | no | integer | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | ChatSearchResponse |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/chat/sessions`

- Summary: List Sessions

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| query | status | no | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | object |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/chat/sessions`

- Summary: Create Session

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | CreateSessionRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 201 | application/json | object |
| 403 | - | EXPERT_NOT_INCLUDED_IN_PLAN |
| 422 | application/json | HTTPValidationError |

### DELETE `/api/v1/chat/sessions/{session_id}`

- Summary: Delete Session

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | session_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | object |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/chat/sessions/{session_id}`

- Summary: Get Session

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | session_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | object |
| 422 | application/json | HTTPValidationError |

### PATCH `/api/v1/chat/sessions/{session_id}/archive`

- Summary: Archive Session

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | session_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | ArchiveSessionRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | object |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/chat/sessions/{session_id}/messages`

- Summary: List Messages

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | session_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | ChatMessagesResponse |
| 422 | application/json | HTTPValidationError |

### PATCH `/api/v1/chat/sessions/{session_id}/pin`

- Summary: Pin Session

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | session_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | PinSessionRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | object |
| 422 | application/json | HTTPValidationError |

### PATCH `/api/v1/chat/sessions/{session_id}/title`

- Summary: Rename Session

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | session_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | RenameSessionRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | object |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/chat/sessions/{session_id}/transcript`

- Summary: Get Transcript

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | session_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | object |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/chat/sessions/{session_id}/turns`

- Summary: Create Turn

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | session_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | ChatTurnRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | - |
| 402 | - | CREDIT_EXHAUSTED |
| 403 | - | EXPERT_NOT_INCLUDED_IN_PLAN |
| 409 | - | CHAT_TURN_ALREADY_RUNNING |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/chat/turns/{turn_id}/cancel`

- Summary: Cancel Turn

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | turn_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | object |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/chat/turns/{turn_id}/citations/{citation_id}/download`

- Summary: Download Citation

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | turn_id | yes | string | - |
| path | citation_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | CitationDownloadResponse |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/chat/turns/{turn_id}/citations/{citation_id}/preview`

- Summary: Preview Citation

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | turn_id | yes | string | - |
| path | citation_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | CitationPreviewResponse |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/chat/turns/{turn_id}/events`

- Summary: Turn Events

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | turn_id | yes | string | - |
| query | after | no | integer \| null | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | - |
| 422 | application/json | HTTPValidationError |

## credits

### GET `/api/v1/credits/current`

- Summary: Get Current Credits

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | CreditSummary |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/tenants/{tenant_id}/credits/adjustments`

- Summary: Adjust Tenant Credits

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | tenant_id | yes | string | - |
| query | userId | no | string \| null | - |
| header | Idempotency-Key | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | CreditAdjustmentRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | CreditLedgerEntry |
| 400 | - | CREDIT_USER_REQUIRED or CREDIT_USER_SCOPE_UNSUPPORTED |
| 409 | - | CREDIT_ADJUSTMENT_EXCEEDS_BALANCE or IDEMPOTENCY_KEY_REUSED |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/tenants/{tenant_id}/credits/current`

- Summary: Get Tenant Current Credits

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | tenant_id | yes | string | - |
| query | userId | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | AdminCreditSummary |
| 400 | - | CREDIT_USER_SCOPE_UNSUPPORTED |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/tenants/{tenant_id}/credits/ledger`

- Summary: List Tenant Credit Ledger

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | tenant_id | yes | string | - |
| query | userId | no | string \| null | - |
| query | page | no | integer | - |
| query | pageSize | no | integer | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | CreditLedgerListResponse |
| 400 | - | CREDIT_USER_SCOPE_UNSUPPORTED |
| 422 | application/json | HTTPValidationError |

## docs

### GET `/api/v1/knowledge-bases/{knowledge_base_id}/docs`

- Summary: List Documents

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | knowledge_base_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | DocumentListResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/knowledge-bases/{knowledge_base_id}/docs/complete-upload`

- Summary: Complete Upload

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | knowledge_base_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | CompleteUploadRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 201 | application/json | Document |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/knowledge-bases/{knowledge_base_id}/docs/complete-uploads`

- Summary: Complete Uploads

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | knowledge_base_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | CompleteUploadsRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | CompleteUploadsResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/knowledge-bases/{knowledge_base_id}/docs/upload-url`

- Summary: Create Upload Url

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | knowledge_base_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | UploadUrlRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | UploadUrlResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/knowledge-bases/{knowledge_base_id}/docs/upload-urls`

- Summary: Create Upload Urls

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | knowledge_base_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | UploadUrlsRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | UploadUrlsResponse |
| 422 | application/json | HTTPValidationError |

### DELETE `/api/v1/knowledge-bases/{knowledge_base_id}/docs/{document_id}`

- Summary: Delete Document

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | knowledge_base_id | yes | string | - |
| path | document_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 204 | - | Successful Response |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/knowledge-bases/{knowledge_base_id}/docs/{document_id}`

- Summary: Get Document

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | knowledge_base_id | yes | string | - |
| path | document_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | Document |
| 422 | application/json | HTTPValidationError |

### PATCH `/api/v1/knowledge-bases/{knowledge_base_id}/docs/{document_id}`

- Summary: Update Document

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | knowledge_base_id | yes | string | - |
| path | document_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | UpdateDocumentRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | Document |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/knowledge-bases/{knowledge_base_id}/docs/{document_id}/complete-upload`

- Summary: Complete Replacement Upload

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | knowledge_base_id | yes | string | - |
| path | document_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | CompleteUploadRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | Document |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/knowledge-bases/{knowledge_base_id}/docs/{document_id}/download-url`

- Summary: Get Download Url

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | knowledge_base_id | yes | string | - |
| path | document_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | DownloadUrlResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/knowledge-bases/{knowledge_base_id}/docs/{document_id}/upload-url`

- Summary: Create Replacement Upload Url

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | knowledge_base_id | yes | string | - |
| path | document_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | UploadUrlRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | UploadUrlResponse |
| 422 | application/json | HTTPValidationError |

## expert-categories

### GET `/api/v1/expert-categories`

- Summary: List Expert Categories

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | ExpertCategoryListResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/expert-categories`

- Summary: Create Expert Category

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | CreateExpertCategoryRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 201 | application/json | ExpertCategory |
| 422 | application/json | HTTPValidationError |

### DELETE `/api/v1/expert-categories/{category_id}`

- Summary: Delete Expert Category

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | category_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 204 | - | Successful Response |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/expert-categories/{category_id}`

- Summary: Get Expert Category

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | category_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | ExpertCategory |
| 422 | application/json | HTTPValidationError |

### PATCH `/api/v1/expert-categories/{category_id}`

- Summary: Update Expert Category

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | category_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | UpdateExpertCategoryRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | ExpertCategory |
| 422 | application/json | HTTPValidationError |

## expert-market

### GET `/api/v1/expert-market/categories`

- Summary: List Market Categories

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | ExpertMarketCategoryListResponse |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/expert-market/experts`

- Summary: List Market Experts

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| query | categoryId | no | string \| null | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | ExpertMarketExpertListResponse |
| 403 | - | Tenant context is required |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/expert-market/experts/{expert_id}`

- Summary: Get Market Expert

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | expert_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | ExpertMarketExpert |
| 403 | - | Tenant context is required |
| 422 | application/json | HTTPValidationError |

## experts

### GET `/api/v1/experts`

- Summary: List Experts

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| query | name | no | string \| null | - |
| query | categoryId | no | string \| null | - |
| query | status | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | ExpertListResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/experts`

- Summary: Create Expert

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | CreateExpertRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 201 | application/json | Expert |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/experts/stats/summary`

- Summary: Get Expert Stats

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | ExpertStatsResponse |
| 422 | application/json | HTTPValidationError |

### DELETE `/api/v1/experts/{expert_id}`

- Summary: Delete Expert

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | expert_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 204 | - | Successful Response |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/experts/{expert_id}`

- Summary: Get Expert

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | expert_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | Expert |
| 422 | application/json | HTTPValidationError |

### PATCH `/api/v1/experts/{expert_id}`

- Summary: Update Expert

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | expert_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | UpdateExpertRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | Expert |
| 422 | application/json | HTTPValidationError |

### PATCH `/api/v1/experts/{expert_id}/status`

- Summary: Update Expert Status

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | expert_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | UpdateExpertStatusRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | Expert |
| 422 | application/json | HTTPValidationError |

## featured-categories

### GET `/api/v1/featured-categories`

- Summary: List Categories

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | FeaturedCategoryListResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/featured-categories`

- Summary: Create Category

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | CreateFeaturedCategoryRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 201 | application/json | FeaturedCategory |
| 422 | application/json | HTTPValidationError |

### PUT `/api/v1/featured-categories/order`

- Summary: Order Categories

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | FeaturedOrderRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | FeaturedCategoryListResponse |
| 422 | application/json | HTTPValidationError |

### DELETE `/api/v1/featured-categories/{category_id}`

- Summary: Delete Category

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | category_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 204 | - | Successful Response |
| 422 | application/json | HTTPValidationError |

### PATCH `/api/v1/featured-categories/{category_id}`

- Summary: Update Category

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | category_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | UpdateFeaturedCategoryRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | FeaturedCategory |
| 422 | application/json | HTTPValidationError |

### PUT `/api/v1/featured-categories/{category_id}/examples/order`

- Summary: Order Examples

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | category_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | FeaturedOrderRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | FeaturedExampleOrderResponse |
| 422 | application/json | HTTPValidationError |

## featured-examples

### GET `/api/v1/featured-examples`

- Summary: List Examples

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| query | categoryId | no | string \| null | - |
| query | status | no | string \| null | - |
| query | reviewState | no | string \| null | - |
| query | keyword | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | FeaturedExampleListResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/featured-examples`

- Summary: Create Example

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | CreateFeaturedExampleRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 201 | application/json | FeaturedExample |
| 422 | application/json | HTTPValidationError |

### DELETE `/api/v1/featured-examples/{example_id}`

- Summary: Delete Example

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | example_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 204 | - | Successful Response |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/featured-examples/{example_id}`

- Summary: Get Example

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | example_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | FeaturedExample |
| 422 | application/json | HTTPValidationError |

### PATCH `/api/v1/featured-examples/{example_id}`

- Summary: Update Example

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | example_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | UpdateFeaturedExampleRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | FeaturedExample |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/featured-examples/{example_id}/review`

- Summary: Review Example

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | example_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | ReviewFeaturedExampleRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | FeaturedExample |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/featured-examples/{example_id}/unlist`

- Summary: Unlist Example

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | example_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | FeaturedExample |
| 422 | application/json | HTTPValidationError |

## featured-market

### GET `/api/v1/featured-market/examples`

- Summary: List Market

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| query | categoryId | no | string \| null | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | FeaturedMarketExampleListResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/featured-market/examples/{example_id}/use`

- Summary: Use Example

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | example_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | FeaturedExampleUseResponse |
| 422 | application/json | HTTPValidationError |

## health

### GET `/health`

- Summary: Health check

#### Input Parameters

No input parameters.

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | object |

## knowledge-bases

### GET `/api/v1/knowledge-bases`

- Summary: List Knowledge Bases

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| query | status | no | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | KnowledgeBaseListResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/knowledge-bases`

- Summary: Create Knowledge Base

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | CreateKnowledgeBaseRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 201 | application/json | KnowledgeBase |
| 422 | application/json | HTTPValidationError |

### DELETE `/api/v1/knowledge-bases/{knowledge_base_id}`

- Summary: Delete Knowledge Base

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | knowledge_base_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 204 | - | Successful Response |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/knowledge-bases/{knowledge_base_id}`

- Summary: Get Knowledge Base

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | knowledge_base_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | KnowledgeBase |
| 422 | application/json | HTTPValidationError |

### PATCH `/api/v1/knowledge-bases/{knowledge_base_id}`

- Summary: Update Knowledge Base

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | knowledge_base_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | UpdateKnowledgeBaseRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | KnowledgeBase |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/knowledge-bases/{knowledge_base_id}/activate`

- Summary: Activate Knowledge Base

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | knowledge_base_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | KnowledgeBase |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/knowledge-bases/{knowledge_base_id}/archive`

- Summary: Archive Knowledge Base

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | knowledge_base_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | KnowledgeBase |
| 422 | application/json | HTTPValidationError |

## knowledge-index

### GET `/api/v1/knowledge-bases/{knowledge_base_id}/index-review`

- Summary: Get Index Review

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | knowledge_base_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | IndexReview |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/knowledge-bases/{knowledge_base_id}/index-review/approve`

- Summary: Approve Index Review

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | knowledge_base_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | ApproveIndexRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | IndexReview |
| 422 | application/json | HTTPValidationError |

## library

### GET `/api/v1/library/delivery/{token}`

- Summary: Agent Delivery

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | token | yes | string | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | - |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/library/files`

- Summary: List Files

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| query | keyword | no | string \| null | - |
| query | type | no | string | - |
| query | page | no | integer | - |
| query | pageSize | no | integer | - |
| query | sort | no | string | - |
| query | lifecycle | no | string | - |
| query | sessionId | no | string \| null | - |
| query | spaceType | no | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | LibraryFileListResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/library/files/complete-upload`

- Summary: Complete Upload

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | LibraryCompleteUploadRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 201 | application/json | LibraryFile |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/library/files/complete-uploads`

- Summary: Complete Uploads

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | LibraryCompleteUploadsRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | LibraryCompleteUploadsResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/library/files/upload-url`

- Summary: Create Upload Url

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | LibraryUploadUrlRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | LibraryUploadUrlResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/library/files/upload-urls`

- Summary: Create Upload Urls

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | LibraryUploadUrlsRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | LibraryUploadUrlsResponse |
| 422 | application/json | HTTPValidationError |

### DELETE `/api/v1/library/files/{file_id}`

- Summary: Delete File

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | file_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | LibraryDeletedResponse |
| 422 | application/json | HTTPValidationError |

### PATCH `/api/v1/library/files/{file_id}`

- Summary: Rename File

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | file_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | LibraryRenameRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | LibraryFile |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/library/files/{file_id}/content`

- Summary: File Content

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | file_id | yes | string | - |
| query | disposition | no | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | - |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/library/files/{file_id}/download`

- Summary: Download File

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | file_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | LibraryDownloadResponse |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/library/files/{file_id}/preview`

- Summary: Preview File

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | file_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | LibraryPreviewResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/library/files/{file_id}/promote`

- Summary: Promote File

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | file_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | LibraryFile |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/library/spaces`

- Summary: List Spaces

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | LibrarySpacesResponse |
| 422 | application/json | HTTPValidationError |

## mcp-connectors

### GET `/api/v1/mcp-connectors`

- Summary: List Mcp Connectors

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | McpConnectorListResponse |
| 422 | application/json | HTTPValidationError |

## models

### GET `/api/v1/models/embedding`

- Summary: Get Embedding Model

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | object |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/models/llm`

- Summary: List Llm Models

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | object |
| 422 | application/json | HTTPValidationError |

## ops

### GET `/api/v1/ops/metrics`

- Summary: Metrics

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | object |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/ops/storage/gc`

- Summary: Run Storage Gc
- Description: Run the object-storage garbage collection passes and report what each reclaimed.

The reclamation methods on DocumentService and LibraryService are otherwise only reachable from
code; this is the operational entry point (call it from a cron via the `system:ops`
permission). Each pass is idempotent and best-effort by object key, so repeated runs are safe
and a partial failure is retried on the next call.

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | object |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/ops/storage/library-usage-reconciliation`

- Summary: Library Usage Reconciliation
- Description: Report Library quota ledger drift without mutating the ledger.

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | object |
| 422 | application/json | HTTPValidationError |

## plan-market

### GET `/api/v1/plan-market/current-subscription`

- Summary: Get Current Subscription

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | CurrentSubscriptionResponse |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/plan-market/plans`

- Summary: List Market Plans

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | PlanListResponse |
| 422 | application/json | HTTPValidationError |

## plans

### GET `/api/v1/plans`

- Summary: List Plans

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | PlanListResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/plans`

- Summary: Create Plan

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | CreatePlanRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 201 | application/json | Plan |
| 422 | application/json | HTTPValidationError |

### DELETE `/api/v1/plans/{plan_id}`

- Summary: Delete Plan

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | plan_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 204 | - | Successful Response |
| 409 | - | CORE_PLAN_DELETE_FORBIDDEN or PLAN_HAS_SUBSCRIPTIONS |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/plans/{plan_id}`

- Summary: Get Plan

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | plan_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | Plan |
| 422 | application/json | HTTPValidationError |

### PATCH `/api/v1/plans/{plan_id}`

- Summary: Update Plan

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | plan_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | UpdatePlanRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | Plan |
| 409 | - | CORE_PLAN_CODE_IMMUTABLE or PLAN_CONFLICT |
| 422 | application/json | HTTPValidationError |

### PUT `/api/v1/plans/{plan_id}/entitlements`

- Summary: Replace Plan Entitlements

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | plan_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | ReplacePlanEntitlementsRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | Plan |
| 422 | application/json | HTTPValidationError |

### PUT `/api/v1/plans/{plan_id}/experts`

- Summary: Replace Plan Experts

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | plan_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | ReplacePlanExpertsRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | Plan |
| 422 | application/json | HTTPValidationError |

### PUT `/api/v1/plans/{plan_id}/prices`

- Summary: Replace Plan Prices

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | plan_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | ReplacePlanPricesRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | Plan |
| 422 | application/json | HTTPValidationError |

## rbac

### GET `/api/v1/rbac/platform/roles`

- Summary: List Platform Roles

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | ListPlatformRolesResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/rbac/platform/users/{user_id}/roles`

- Summary: Grant Platform Role

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | user_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | GrantPlatformRoleRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 204 | - | Successful Response |
| 422 | application/json | HTTPValidationError |

### DELETE `/api/v1/rbac/platform/users/{user_id}/roles/{role}`

- Summary: Revoke Platform Role

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | user_id | yes | string | - |
| path | role | yes | PlatformRole | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 204 | - | Successful Response |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/rbac/tenant/users`

- Summary: List Tenant Users

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | ListUsersResponse |
| 422 | application/json | HTTPValidationError |

### DELETE `/api/v1/rbac/tenant/users/{user_id}`

- Summary: Revoke Tenant Member

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | user_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 204 | - | Successful Response |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/rbac/tenant/users/{user_id}/roles`

- Summary: Grant Tenant Role

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | user_id | yes | string | - |
| header | x-tenant-id | no | string \| null | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | GrantTenantRoleRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 204 | - | Successful Response |
| 422 | application/json | HTTPValidationError |

## skills

### GET `/api/v1/skills`

- Summary: List Skills

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| query | tags | no | array[string] | - |
| query | search | no | string \| null | - |
| query | limit | no | integer | - |
| query | offset | no | integer | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | SkillListResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/skills`

- Summary: Upload Skill

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |
| body | multipart/form-data | yes | Body_upload_skill_api_v1_skills_post | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 201 | application/json | Skill |
| 422 | application/json | HTTPValidationError |

### DELETE `/api/v1/skills/{slug}`

- Summary: Delete Skill

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | slug | yes | string | - |
| query | delete_files | no | boolean | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 204 | - | Successful Response |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/skills/{slug}`

- Summary: Get Skill

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | slug | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | Skill |
| 422 | application/json | HTTPValidationError |

### PUT `/api/v1/skills/{slug}`

- Summary: Update Skill

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | slug | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | SkillMetadataUpdate | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | Skill |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/skills/{slug}/file`

- Summary: Get Skill File

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | slug | yes | string | - |
| query | path | no | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | - |
| 422 | application/json | HTTPValidationError |

## storage

### GET `/api/v1/storage/objects/{token}`

- Summary: Get Object

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | token | yes | string | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | - |
| 422 | application/json | HTTPValidationError |

### PUT `/api/v1/storage/objects/{token}`

- Summary: Put Object

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | token | yes | string | - |
| header | content-type | no | string \| null | - |
| header | content-length | no | integer \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 204 | - | Successful Response |
| 422 | application/json | HTTPValidationError |

## tenants

### GET `/api/v1/tenants`

- Summary: List Tenants

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| query | search | no | string \| null | - |
| query | type | no | string \| null | - |
| query | subscriptionType | no | string \| null | - |
| query | subscriptionStatus | no | string \| null | - |
| query | sort | no | string \| null | - |
| query | page | no | integer | - |
| query | pageSize | no | integer | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | TenantListResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/tenants`

- Summary: Create Tenant

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | CreateTenantRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 201 | application/json | Tenant |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/tenants/filter-options`

- Summary: Tenant Filter Options

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | TenantFilterOptionsResponse |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/tenants/{tenant_id}`

- Summary: Get Tenant

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | tenant_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | Tenant |
| 422 | application/json | HTTPValidationError |

### PATCH `/api/v1/tenants/{tenant_id}`

- Summary: Update Tenant

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | tenant_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | UpdateTenantRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | Tenant |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/tenants/{tenant_id}/members`

- Summary: List Tenant Members

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | tenant_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | TenantMemberListResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/tenants/{tenant_id}/members`

- Summary: Add Tenant Member

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | tenant_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | AddTenantMemberRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 201 | application/json | TenantMember |
| 422 | application/json | HTTPValidationError |

### DELETE `/api/v1/tenants/{tenant_id}/members/{user_id}`

- Summary: Remove Tenant Member

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | tenant_id | yes | string | - |
| path | user_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 204 | - | Successful Response |
| 422 | application/json | HTTPValidationError |

### PATCH `/api/v1/tenants/{tenant_id}/members/{user_id}`

- Summary: Update Tenant Member

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | tenant_id | yes | string | - |
| path | user_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | UpdateTenantMemberRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | TenantMember |
| 422 | application/json | HTTPValidationError |

### PATCH `/api/v1/tenants/{tenant_id}/status`

- Summary: Update Tenant Status

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | tenant_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | UpdateTenantStatusRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | Tenant |
| 422 | application/json | HTTPValidationError |

### PATCH `/api/v1/tenants/{tenant_id}/subscription`

- Summary: Update Tenant Subscription

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | tenant_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | UpdateTenantSubscriptionRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | Tenant |
| 409 | - | PLAN_CREDIT_ENTITLEMENT_REQUIRED |
| 422 | application/json | HTTPValidationError |

## users

### GET `/api/v1/users`

- Summary: List Users

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| query | search | no | string \| null | - |
| query | subscriptionStatus | no | string \| null | - |
| query | subscriptionType | no | string \| null | - |
| query | sort | no | string \| null | - |
| query | page | no | integer | - |
| query | pageSize | no | integer | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | ListManagedUsersResponse |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/users/platform`

- Summary: List Platform Users

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | ListUsersResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/users/platform`

- Summary: Create Platform User

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | CreatePlatformUserRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 201 | application/json | CreatePlatformUserResponse |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/users/platform/activate`

- Summary: Activate Platform User

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| body | application/json | yes | PlatformUserActivateRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | object |
| 422 | application/json | HTTPValidationError |

### POST `/api/v1/users/register`

- Summary: Register

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| body | application/json | yes | RegisterRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 201 | application/json | object |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/users/{user_id}`

- Summary: Get User

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | user_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | UserDetail |
| 422 | application/json | HTTPValidationError |

### PATCH `/api/v1/users/{user_id}`

- Summary: Update User

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | user_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | UpdateUserRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | UserDetail |
| 422 | application/json | HTTPValidationError |

### PATCH `/api/v1/users/{user_id}/status`

- Summary: Update User Status

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | user_id | yes | string | - |
| header | Authorization | no | string \| null | - |
| body | application/json | yes | UpdateUserStatusRequest | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | UserDetail |
| 422 | application/json | HTTPValidationError |

### GET `/api/v1/users/{user_id}/tenants`

- Summary: List User Tenants

#### Input Parameters

| Location | Name | Required | Type | Description |
| --- | --- | --- | --- | --- |
| path | user_id | yes | string | - |
| header | Authorization | no | string \| null | - |

#### Response

| Status | Content Type | Schema |
| --- | --- | --- |
| 200 | application/json | ListUserTenantsResponse |
| 422 | application/json | HTTPValidationError |

## Schemas

### `AddTenantMemberRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| userId | yes | string | - |
| role | no | TenantRole | - |

### `AdminCreditSummary`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| tenantId | yes | string | - |
| planId | yes | string | - |
| planCode | yes | string | - |
| planName | yes | string | - |
| periodStart | yes | string | - |
| periodEnd | yes | string | - |
| monthlyCreditLimit | yes | integer | - |
| grantedCredits | yes | integer | - |
| adjustmentCredits | yes | integer | - |
| estimatedUsedCredits | yes | integer | - |
| deductedCredits | yes | integer | - |
| remainingCredits | yes | integer | - |
| enforcementEnabled | yes | boolean | - |
| ledgerBalance | yes | integer | - |
| overdrawnCredits | yes | integer | - |

### `ApproveIndexRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| batchToken | yes | string | - |

### `ArchiveSessionRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| archived | no | boolean | - |

### `AuditActor`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| userId | yes | string | - |
| name | yes | string | - |
| email | yes | string | - |
| platformRoles | no | array[string] | - |

### `AuditCategory`

`{"type": "string", "enum": ["auth", "platform_user", "user", "platform_role", "tenant", "tenant_member", "knowledge_base", "document", "skill", "expert_category", "expert", "featured_example", "plan", "library"], "title": "AuditCategory"}`

### `AuditChange`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| before | no | {"title": "Before"} | - |
| after | no | {"title": "After"} | - |

### `AuditEvent`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| requestId | yes | string | - |
| occurredAt | yes | string | - |
| category | yes | AuditCategory | - |
| action | yes | string | - |
| operationType | yes | AuditOperationType | - |
| actor | yes | AuditActor | - |
| tenant | no | AuditTenant \| null | - |
| resource | yes | AuditResource | - |
| changes | no | object | - |
| metadata | no | object | - |
| clientIp | no | null | - |

### `AuditEventListResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[AuditEvent] | - |
| total | yes | integer | - |
| page | yes | integer | - |
| pageSize | yes | integer | - |

### `AuditOperationType`

`{"type": "string", "enum": ["create", "read", "update", "delete", "login", "grant", "revoke", "upload"], "title": "AuditOperationType"}`

### `AuditResource`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| type | yes | string | - |
| id | yes | string | - |
| name | no | string \| null | - |

### `AuditTenant`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| name | yes | string | - |

### `BatchItemError`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| code | yes | string | - |
| message | yes | string | - |
| details | no | object | - |

### `Body_upload_current_avatar_api_v1_auth_me_avatar_put`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| file | yes | string | - |

### `Body_upload_skill_api_v1_skills_post`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| file | yes | string | - |
| slug | no | string \| null | - |

### `ChatMessagesResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | no | array[ChatTurnResponse] | - |

### `ChatRetrievalSource`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| citationId | no | string \| null | - |
| citationIds | no | array[string] | - |
| knowledgeBaseId | no | string \| null | - |
| knowledgeBaseName | no | string \| null | - |
| documentId | no | string \| null | - |
| fileName | yes | string | - |
| pageNumber | no | integer \| null | - |
| mimeType | no | string \| null | - |
| hitText | no | string \| null | - |
| locator | no | object | - |
| previewUrl | no | string \| null | - |
| downloadUrl | no | string \| null | - |
| available | no | boolean | - |

### `ChatSearchItem`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| sessionId | yes | string | - |
| title | no | string \| null | - |
| matchedTurnId | yes | string | - |
| matchedType | yes | string | - |
| snippet | yes | string | - |

### `ChatSearchResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[ChatSearchItem] | - |
| total | yes | integer | - |
| limit | yes | integer | - |
| offset | yes | integer | - |

### `ChatTurnRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| question | yes | string | - |
| webSearchEnabled | no | boolean \| null | Routes ACP turns to the search prefix with search_mode=auto when true; otherwise uses the default prefix with search_mode=off. |
| attachmentFileIds | no | array[string] \| null | Completed library_files ids referenced by this turn (docs/LIBRARY_FILE_LIFECYCLE.md §7.3). Each is authorized per §5; a temporary file must belong to this session and not be expired. |

### `ChatTurnResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| sessionId | yes | string | - |
| requestText | yes | string | - |
| reasoningText | no | string \| null | - |
| responseText | no | string \| null | - |
| model | no | string \| null | - |
| expertId | no | string \| null | - |
| runtimeType | no | string \| null | - |
| status | yes | string | - |
| stopReason | no | string \| null | - |
| errorMessage | no | string \| null | - |
| attachments | no | array[object] | - |
| retrievalRefs | no | array[ChatRetrievalSource] | - |
| createdAt | yes | string | - |
| completedAt | no | string \| null | - |

### `CitationDownloadResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| citationId | yes | string | - |
| fileName | yes | string | - |
| downloadUrl | yes | string | - |
| expiresAt | yes | string | - |

### `CitationPreviewResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| citationId | yes | string | - |
| knowledgeBaseId | yes | string | - |
| knowledgeBaseName | yes | string | - |
| documentId | yes | string | - |
| fileName | yes | string | - |
| pageNumber | no | integer \| null | - |
| hitText | yes | string | - |
| locator | no | object | - |
| previewType | yes | string | - |
| content | no | string \| null | - |
| url | no | string \| null | - |
| mimeType | no | string \| null | - |
| expiresAt | no | string \| null | - |

### `CompleteUploadRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| uploadSessionId | yes | string | - |
| etag | no | string \| null | - |
| fileSizeBytes | no | integer \| null | - |

### `CompleteUploadResult`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| uploadSessionId | yes | string | - |
| status | yes | string | - |
| document | no | Document \| null | - |
| error | no | BatchItemError \| null | - |

### `CompleteUploadsRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[CompleteUploadRequest] | - |

### `CompleteUploadsResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[CompleteUploadResult] | - |

### `CreateExpertCategoryRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| name | yes | string | - |
| description | no | string \| null | - |

### `CreateExpertRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| name | yes | string | - |
| categoryId | yes | string | - |
| abilityIntro | yes | string | - |
| instructions | no | string | - |
| runtimeConfig | no | object | - |
| mcpConnectorIds | no | array[string] | - |
| skillRuntimeTargets | no | object | - |
| tags | no | array[string] | - |
| marketLabels | no | array[string] | - |
| skillIds | no | array[string] | - |
| knowledgeBaseIds | no | array[string] | - |
| guideQuestions | no | array[string] | - |
| summonButtonText | no | string \| null | - |

### `CreateFeaturedCategoryRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| name | yes | string | - |
| tone | yes | string | - |

### `CreateFeaturedExampleRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| categoryId | yes | string | - |
| question | yes | string | - |
| reviewCycleDays | no | integer \| null | - |

### `CreateKnowledgeBaseRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| name | yes | string | - |
| description | no | string \| null | - |
| metadata | no | object | - |

### `CreatePlanRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| code | no | string \| null | - |
| name | yes | string | - |
| level | yes | integer | - |
| description | yes | string | - |
| typeLabel | no | string \| null | - |
| subtitle | no | string \| null | - |
| badgeLabel | no | string \| null | - |
| highlightItems | no | array[string] | - |
| upgradeRules | no | object | - |
| status | no | string | - |
| isRecommended | no | boolean | - |
| sortOrder | no | integer | - |

### `CreatePlatformUserRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| email | yes | string | - |
| name | yes | string | - |
| roles | no | array[PlatformRole] | - |

### `CreatePlatformUserResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| email | yes | string | - |
| name | yes | string | - |
| status | yes | string | - |
| platformRoles | yes | array[PlatformRole] | - |
| activationToken | yes | string | - |
| activationExpiresAt | yes | string | - |

### `CreateSessionRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| title | no | string \| null | - |
| expertId | no | string \| null | - |
| runtimeType | no | string \| null | - |

### `CreateTenantRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| name | yes | string | - |
| slug | no | string \| null | - |
| ownerUserId | yes | string | - |

### `CreditAdjustmentRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| amount | yes | integer | - |
| reason | yes | string | - |

### `CreditLedgerEntry`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| periodId | yes | string | - |
| tenantId | yes | string | - |
| beneficiaryUserId | no | string \| null | - |
| entryType | yes | string | - |
| amount | yes | integer | - |
| referenceId | no | string \| null | - |
| idempotencyKey | no | string \| null | - |
| actorUserId | no | string \| null | - |
| reason | no | string \| null | - |
| createdAt | yes | string | - |

### `CreditLedgerListResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[CreditLedgerEntry] | - |
| total | yes | integer | - |
| page | yes | integer | - |
| pageSize | yes | integer | - |

### `CreditSummary`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| tenantId | yes | string | - |
| planId | yes | string | - |
| planCode | yes | string | - |
| planName | yes | string | - |
| periodStart | yes | string | - |
| periodEnd | yes | string | - |
| monthlyCreditLimit | yes | integer | - |
| grantedCredits | yes | integer | - |
| adjustmentCredits | yes | integer | - |
| estimatedUsedCredits | yes | integer | - |
| deductedCredits | yes | integer | - |
| remainingCredits | yes | integer | - |
| enforcementEnabled | yes | boolean | - |

### `CurrentSubscriptionResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| subscription | yes | TenantSubscription | - |
| plan | yes | Plan | - |

### `CurrentUserProfile`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| email | yes | string | - |
| name | yes | string | - |
| preferredLocale | no | string \| null | - |
| avatarUrl | no | string \| null | - |
| avatarUrlExpiresAt | no | string \| null | - |
| updatedAt | yes | string | - |

### `Document`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| knowledgeBaseId | yes | string | - |
| fileName | yes | string | - |
| fileType | yes | string | - |
| mimeType | no | string \| null | - |
| fileSizeBytes | yes | integer | - |
| storageKey | yes | string | - |
| contentHash | no | string \| null | - |
| sourceSha | no | string \| null | - |
| indexedSha | no | string \| null | - |
| indexDocumentId | no | string \| null | - |
| indexPipelineVersion | no | string \| null | - |
| parseStatus | yes | string | - |
| indexStatus | yes | string | - |
| parseError | no | string \| null | - |
| lastError | no | string \| null | - |
| metadata | no | object | - |
| createdAt | yes | string | - |
| updatedAt | yes | string | - |

### `DocumentListResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[Document] | - |

### `DownloadUrlResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| method | no | string | - |
| downloadUrl | yes | string | - |
| expiresAt | yes | string | - |

### `Expert`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| name | yes | string | - |
| categoryId | yes | string | - |
| categoryName | yes | string | - |
| abilityIntro | yes | string | - |
| instructions | no | string | - |
| runtimeConfig | no | object | - |
| mcpConnectorIds | no | array[string] | - |
| skillRuntimeTargets | no | object | - |
| tags | no | array[string] | - |
| marketLabels | no | array[string] | - |
| status | yes | string | - |
| skillIds | no | array[string] | - |
| knowledgeBaseIds | no | array[string] | - |
| guideQuestions | no | array[string] | - |
| summonButtonText | no | string \| null | - |
| createdAt | yes | string | - |
| updatedAt | yes | string | - |

### `ExpertCategory`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| name | yes | string | - |
| description | no | string \| null | - |
| createdAt | yes | string | - |
| updatedAt | yes | string | - |

### `ExpertCategoryListResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[ExpertCategory] | - |

### `ExpertListResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[Expert] | - |

### `ExpertMarketCategory`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| name | yes | string | - |
| description | no | string \| null | - |

### `ExpertMarketCategoryListResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[ExpertMarketCategory] | - |

### `ExpertMarketExpert`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| name | yes | string | - |
| categoryId | yes | string | - |
| categoryName | yes | string | - |
| abilityIntro | yes | string | - |
| tags | no | array[string] | - |
| marketLabels | no | array[string] | - |
| guideQuestions | no | array[string] | - |
| summonButtonText | no | string \| null | - |
| isAccessible | yes | boolean | - |

### `ExpertMarketExpertListResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[ExpertMarketExpert] | - |

### `ExpertRuntimeTarget`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| enabled | no | boolean | - |
| model | no | string | - |
| maxInstances | no | integer | - |
| idleTtlSeconds | no | integer | - |
| turnTimeoutSeconds | no | integer | - |
| permissionMode | no | string | - |
| requireVirtualKey | no | boolean | - |
| environment | no | object | - |

### `ExpertStatsResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| total | yes | integer | - |
| published | yes | integer | - |
| draft | yes | integer | - |
| unlisted | yes | integer | - |

### `FeaturedCategory`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| name | yes | string | - |
| short | yes | string | - |
| tone | yes | string | - |
| sortOrder | yes | integer | - |
| createdAt | yes | string | - |
| updatedAt | yes | string | - |

### `FeaturedCategoryListResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[FeaturedCategory] | - |

### `FeaturedExample`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| categoryId | yes | string | - |
| question | yes | string | - |
| sortOrder | yes | integer | - |
| status | yes | string | - |
| reviewCycleDays | yes | integer \| null | - |
| reviewState | yes | string | - |
| reviewedAt | yes | string \| null | - |
| expiresAt | yes | string \| null | - |
| rejectReason | yes | string \| null | - |
| clickCount | yes | integer | - |
| createdBy | yes | string \| null | - |
| authorName | yes | string \| null | - |
| updatedBy | yes | string \| null | - |
| reviewedBy | yes | string \| null | - |
| createdAt | yes | string | - |
| updatedAt | yes | string | - |

### `FeaturedExampleCounts`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| total | yes | integer | - |
| live | yes | integer | - |
| pending | yes | integer | - |
| reviewing | yes | integer | - |
| rejected | yes | integer | - |
| unlisted | yes | integer | - |
| expiring | yes | integer | - |
| expired | yes | integer | - |

### `FeaturedExampleListResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[FeaturedExample] | - |
| counts | yes | FeaturedExampleCounts | - |

### `FeaturedExampleOrderResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[FeaturedExample] | - |

### `FeaturedExampleUseResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| question | yes | string | - |
| clickCount | yes | integer | - |

### `FeaturedMarketExample`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| question | yes | string | - |
| categoryId | yes | string | - |
| categoryName | yes | string | - |
| categoryTone | yes | string | - |
| sortOrder | yes | integer | - |
| clickCount | yes | integer | - |

### `FeaturedMarketExampleListResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[FeaturedMarketExample] | - |

### `FeaturedOrderRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| ids | yes | array[string] | - |

### `FilterOption`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| value | yes | string | - |
| label | yes | string | - |

### `GrantPlatformRoleRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| role | yes | PlatformRole | - |

### `GrantTenantRoleRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| role | yes | TenantRole | - |

### `HTTPValidationError`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| detail | no | array[ValidationError] | - |

### `IndexReview`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| knowledgeBaseId | yes | string | - |
| status | yes | string | - |
| thresholdBytes | yes | integer | - |
| documentCount | no | integer | - |
| totalSizeBytes | no | integer | - |
| batchToken | no | string \| null | - |
| documents | no | array[IndexReviewDocument] | - |

### `IndexReviewDocument`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| documentId | yes | string | - |
| fileName | yes | string | - |
| fileSizeBytes | yes | integer | - |

### `KnowledgeBase`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| ownerUserId | no | string \| null | - |
| ownerUserName | no | string \| null | - |
| name | yes | string | - |
| description | no | string \| null | - |
| status | yes | string | - |
| indexStatus | no | string | - |
| indexError | no | string \| null | - |
| indexWorkspace | no | string \| null | - |
| metadata | no | object | - |
| createdAt | yes | string | - |
| updatedAt | yes | string | - |

### `KnowledgeBaseListResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[KnowledgeBase] | - |

### `LibraryCompleteUploadRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| uploadSessionId | yes | string | - |
| contentHash | no | string \| null | - |
| lifecycle | no | string | - |

### `LibraryCompleteUploadResult`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| status | yes | string | - |
| item | no | LibraryFile \| null | - |
| error | no | object \| null | - |

### `LibraryCompleteUploadsRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[LibraryCompleteUploadRequest] | - |

### `LibraryCompleteUploadsResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[LibraryCompleteUploadResult] | - |

### `LibraryDeletedResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| status | no | string | - |

### `LibraryDownloadResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| method | no | string | - |
| downloadUrl | yes | string | - |
| expiresAt | no | string \| null | - |

### `LibraryFile`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| name | yes | string | - |
| mimeType | no | string \| null | - |
| type | yes | string | - |
| sizeBytes | yes | integer | - |
| sizeLabel | yes | string | - |
| lifecycle | no | string | - |
| expiresAt | no | string \| null | - |
| updatedAt | yes | string | - |
| createdAt | yes | string | - |
| previewSupported | yes | boolean | - |
| spaceType | no | string | - |
| ownerUserId | no | string \| null | - |
| ownerTenantId | no | string \| null | - |
| uploadedByUserId | no | string \| null | - |
| capabilities | no | object | - |

### `LibraryFileListResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[LibraryFile] | - |
| total | yes | integer | - |
| page | yes | integer | - |
| pageSize | yes | integer | - |

### `LibraryPreviewResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| previewType | yes | string | - |
| url | no | string \| null | - |
| content | no | string \| null | - |
| mimeType | no | string \| null | - |
| expiresAt | no | string \| null | - |

### `LibraryRenameRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| name | yes | string | - |

### `LibrarySpace`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| spaceType | yes | string | - |
| status | yes | string | - |
| quotaBytes | yes | integer | - |
| usedBytes | yes | integer | - |
| reservedBytes | yes | integer | - |
| remainingBytes | yes | integer | - |
| capabilities | no | object | - |

### `LibrarySpacesResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[LibrarySpace] | - |

### `LibraryUploadUrlRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| fileName | yes | string | - |
| mimeType | no | string \| null | - |
| fileSizeBytes | yes | integer | - |
| contentHash | no | string \| null | - |
| spaceType | no | string | - |

### `LibraryUploadUrlResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| uploadSessionId | yes | string | - |
| fileId | yes | string | - |
| method | no | string | - |
| uploadUrl | yes | string | - |
| headers | no | object | - |
| objectKey | yes | string | - |
| expiresAt | yes | string | - |
| spaceType | yes | string | - |
| nameConflict | no | boolean | - |
| suggestedName | yes | string | - |

### `LibraryUploadUrlResult`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| status | yes | string | - |
| item | no | LibraryUploadUrlResponse \| null | - |
| error | no | object \| null | - |

### `LibraryUploadUrlsRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[LibraryUploadUrlRequest] | - |

### `LibraryUploadUrlsResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[LibraryUploadUrlResult] | - |

### `ListManagedUsersResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[UserSummary] | - |
| total | no | integer | - |
| page | no | integer | - |
| pageSize | no | integer | - |

### `ListPlatformRolesResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[PlatformRoleSummary] | - |

### `ListUserTenantsResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[UserTenantSummary] | - |

### `ListUsersResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[UserAccessSummary] | - |

### `LoginRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| email | yes | string | - |
| password | yes | string | - |
| tenantId | no | string \| null | - |

### `LogoutRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| refreshToken | yes | string | - |

### `McpConnector`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| name | yes | string | - |
| description | yes | string | - |
| transport | yes | string | - |

### `McpConnectorListResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[McpConnector] | - |

### `PasswordResetConfirmRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| email | yes | string | - |
| code | yes | string | - |
| newPassword | yes | string | - |

### `PasswordResetMessageResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| message | yes | string | - |

### `PasswordResetRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| email | yes | string | - |
| locale | no | string | - |

### `PinSessionRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| isPinned | no | boolean | - |

### `Plan`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| code | yes | string | - |
| name | yes | string | - |
| level | yes | integer | - |
| description | yes | string | - |
| typeLabel | no | string \| null | - |
| subtitle | no | string \| null | - |
| badgeLabel | no | string \| null | - |
| highlightItems | no | array[string] | - |
| upgradeRules | no | object | - |
| status | yes | string | - |
| isRecommended | yes | boolean | - |
| sortOrder | yes | integer | - |
| subscriptionCount | no | integer | - |
| prices | no | array[PlanPrice] | - |
| entitlements | no | PlanEntitlements \| null | - |
| expertIds | no | array[string] | - |
| createdAt | yes | string | - |
| updatedAt | yes | string | - |

### `PlanEntitlements`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| planId | yes | string | - |
| monthlyCreditLimit | yes | integer | - |
| allExperts | yes | boolean | - |
| seatLimit | yes | integer | - |
| personalLibraryQuotaBytes | yes | integer | - |
| teamLibraryQuotaBytes | yes | integer | - |
| teamLibraryEnabled | yes | boolean | - |
| singleTurnTokenLimit | no | integer \| null | - |
| modelTiers | no | array[string] | - |
| features | no | object | - |
| createdAt | yes | string | - |
| updatedAt | yes | string | - |

### `PlanListResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[Plan] | - |

### `PlanPrice`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| planId | yes | string | - |
| billingPeriod | yes | string | - |
| currency | yes | string | - |
| amountCents | yes | integer | - |
| discountLabel | no | string \| null | - |
| isEnabled | yes | boolean | - |
| createdAt | yes | string | - |
| updatedAt | yes | string | - |

### `PlatformRole`

`{"type": "string", "enum": ["admin", "expert", "operator"], "title": "PlatformRole"}`

### `PlatformRoleSummary`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| role | yes | PlatformRole | - |
| name | yes | string | - |
| permissions | yes | array[string] | - |

### `PlatformUserActivateRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| token | yes | string | - |
| newPassword | yes | string | - |
| name | no | string \| null | - |

### `RefreshRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| refreshToken | yes | string | - |
| tenantId | no | string \| null | - |

### `RegisterRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| email | yes | string | - |
| password | yes | string | - |
| name | yes | string | - |

### `RenameSessionRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| title | yes | string | - |

### `ReplacePlanEntitlementsRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| monthlyCreditLimit | yes | integer | - |
| allExperts | yes | boolean | - |
| seatLimit | yes | integer | - |
| personalLibraryQuotaBytes | no | integer \| null | - |
| teamLibraryQuotaBytes | no | integer \| null | - |
| teamLibraryEnabled | no | boolean \| null | - |
| singleTurnTokenLimit | no | integer \| null | - |
| modelTiers | no | array[string] | - |
| features | no | object | - |

### `ReplacePlanExpertsRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| expertIds | no | array[string] | - |

### `ReplacePlanPriceRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| billingPeriod | yes | string | - |
| currency | yes | string | - |
| amountCents | yes | integer | - |
| discountLabel | no | string \| null | - |
| isEnabled | no | boolean | - |

### `ReplacePlanPricesRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | no | array[ReplacePlanPriceRequest] | - |

### `ResolvePermissionRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| outcome | no | string \| null | - |
| optionId | no | string \| null | - |

### `ReviewFeaturedExampleRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| decision | yes | string | - |
| expectedUpdatedAt | yes | string | - |
| reason | no | string \| null | - |

### `SecretReference`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| secretRef | yes | string | - |

### `Skill`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| slug | yes | string | - |
| name | yes | string | - |
| description | yes | string | - |
| version | no | string \| null | - |
| allowedTools | no | array[string] | - |
| filePaths | no | array[string] | - |
| tags | no | array[string] | - |
| storageUri | yes | string | - |
| createdAt | yes | string | - |
| updatedAt | yes | string | - |

### `SkillListResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[Skill] | - |
| total | yes | integer | - |
| limit | yes | integer | - |
| offset | yes | integer | - |
| hasMore | yes | boolean | - |

### `SkillMetadataUpdate`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| name | no | string \| null | - |
| description | no | string \| null | - |
| version | no | string \| null | - |
| allowedTools | no | array[string] \| null | - |
| tags | no | array[string] \| null | - |

### `Tenant`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| type | yes | string | - |
| name | yes | string | - |
| slug | yes | string | - |
| ownerUserId | no | string \| null | - |
| ownerUserName | no | string \| null | - |
| ownerUserEmail | no | string \| null | - |
| status | yes | string | - |
| memberCount | yes | integer | - |
| currentSubscription | no | TenantSubscriptionSummary \| null | - |
| currentPlan | no | TenantPlanSummary \| null | - |
| monthlyCredits | no | TenantMonthlyCreditsSummary | - |
| orderSummary | no | TenantOrderSummary | - |
| members | no | array[TenantMember] | - |
| createdAt | yes | string | - |
| updatedAt | yes | string | - |

### `TenantFilterOptionsResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| tenantTypes | yes | array[string] | - |
| subscriptionStatuses | yes | array[string] | - |
| subscriptionTypes | yes | array[FilterOption] | - |

### `TenantListResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[Tenant] | - |
| total | no | integer | - |
| page | no | integer | - |
| pageSize | no | integer | - |

### `TenantMember`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| userId | yes | string | - |
| email | yes | string | - |
| name | yes | string | - |
| status | yes | string | - |
| role | yes | TenantRole | - |
| joinedAt | yes | string | - |

### `TenantMemberListResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[TenantMember] | - |

### `TenantMonthlyCreditsSummary`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| monthlyCreditLimit | no | integer | - |
| estimatedUsedCredits | no | integer | - |
| deductedCredits | no | integer | - |
| remainingCredits | no | integer | - |
| enforcementEnabled | no | boolean | - |

### `TenantOrderItem`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| orderNo | yes | string | - |
| planName | no | string \| null | - |
| billingPeriod | no | string \| null | - |
| amountCents | no | integer | - |
| paidAt | no | string \| null | - |
| status | yes | string | - |

### `TenantOrderSummary`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| totalAmountCents | no | integer | - |
| orderCount | no | integer | - |
| recentOrders | no | array[TenantOrderItem] | - |

### `TenantPlanSummary`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| code | yes | string | - |
| name | yes | string | - |
| typeLabel | no | string \| null | - |
| billingPeriod | yes | string | - |
| priceLabel | no | string \| null | - |
| priceSnapshot | no | object | - |
| entitlementsSnapshot | no | object | - |

### `TenantRole`

`{"type": "string", "enum": ["admin", "member"], "title": "TenantRole"}`

### `TenantSubscription`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| tenantId | yes | string | - |
| planId | yes | string | - |
| status | yes | string | - |
| billingPeriod | yes | string | - |
| currentPeriodStart | yes | string | - |
| currentPeriodEnd | no | string \| null | - |
| cancelAtPeriodEnd | yes | boolean | - |
| createdAt | yes | string | - |
| updatedAt | yes | string | - |

### `TenantSubscriptionSummary`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| subscriptionId | yes | string | - |
| planId | yes | string | - |
| planCode | yes | string | - |
| planName | yes | string | - |
| billingPeriod | yes | string | - |
| status | yes | string | - |
| rawStatus | yes | string | - |
| currentPeriodStart | yes | string | - |
| currentPeriodEnd | no | string \| null | - |
| daysUntilExpiry | no | integer \| null | - |
| cancelAtPeriodEnd | yes | boolean | - |
| autoRenew | yes | boolean | - |
| priceLabel | no | string \| null | - |

### `UpdateCurrentUserProfileRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| name | no | string \| null | - |
| preferredLocale | no | string \| null | - |

### `UpdateDocumentRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| fileName | no | string \| null | - |
| metadata | no | object \| null | - |

### `UpdateExpertCategoryRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| name | no | string \| null | - |
| description | no | string \| null | - |

### `UpdateExpertRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| name | no | string \| null | - |
| categoryId | no | string \| null | - |
| abilityIntro | no | string \| null | - |
| instructions | no | string \| null | - |
| runtimeConfig | no | object \| null | - |
| mcpConnectorIds | no | array[string] \| null | - |
| skillRuntimeTargets | no | object \| null | - |
| tags | no | array[string] \| null | - |
| marketLabels | no | array[string] \| null | - |
| skillIds | no | array[string] \| null | - |
| knowledgeBaseIds | no | array[string] \| null | - |
| guideQuestions | no | array[string] \| null | - |
| summonButtonText | no | string \| null | - |

### `UpdateExpertStatusRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| status | yes | string | - |

### `UpdateFeaturedCategoryRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| name | no | string \| null | - |
| tone | no | string \| null | - |

### `UpdateFeaturedExampleRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| categoryId | no | string \| null | - |
| question | no | string \| null | - |
| reviewCycleDays | no | integer \| null | - |

### `UpdateKnowledgeBaseRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| name | no | string \| null | - |
| description | no | string \| null | - |
| metadata | no | object \| null | - |

### `UpdatePlanRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| code | no | string \| null | - |
| name | no | string \| null | - |
| level | no | integer \| null | - |
| description | no | string \| null | - |
| typeLabel | no | string \| null | - |
| subtitle | no | string \| null | - |
| badgeLabel | no | string \| null | - |
| highlightItems | no | array[string] \| null | - |
| upgradeRules | no | object \| null | - |
| status | no | string \| null | - |
| isRecommended | no | boolean \| null | - |
| sortOrder | no | integer \| null | - |

### `UpdateTenantMemberRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| role | yes | TenantRole | - |

### `UpdateTenantRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| name | no | string \| null | - |
| slug | no | string \| null | - |
| ownerUserId | no | string \| null | - |

### `UpdateTenantStatusRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| status | yes | string | - |

### `UpdateTenantSubscriptionRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| planId | yes | string | - |
| billingPeriod | yes | string | - |
| status | no | string | - |
| currentPeriodStart | no | string \| null | - |
| currentPeriodEnd | no | string \| null | - |
| cancelAtPeriodEnd | no | boolean | - |

### `UpdateUserRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| name | no | string \| null | - |

### `UpdateUserStatusRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| status | yes | string | - |

### `UploadUrlRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| fileName | yes | string | - |
| mimeType | no | string \| null | - |
| fileSizeBytes | yes | integer | - |
| contentHash | no | string \| null | - |

### `UploadUrlResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| uploadSessionId | yes | string | - |
| documentId | yes | string | - |
| method | no | string | - |
| uploadUrl | yes | string | - |
| headers | no | object | - |
| objectKey | yes | string | - |
| expiresAt | yes | string | - |

### `UploadUrlResult`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| fileName | yes | string | - |
| status | yes | string | - |
| upload | no | UploadUrlResponse \| null | - |
| error | no | BatchItemError \| null | - |

### `UploadUrlsRequest`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| files | yes | array[UploadUrlRequest] | - |

### `UploadUrlsResponse`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| items | yes | array[UploadUrlResult] | - |

### `UserAccessSummary`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| email | yes | string | - |
| name | yes | string | - |
| status | yes | string | - |
| activeTenantId | no | string \| null | - |
| tenantRoles | yes | array[TenantRole] | - |
| tenantPermissions | yes | array[string] | - |
| platformRoles | yes | array[PlatformRole] | - |
| platformPermissions | yes | array[string] | - |
| createdAt | yes | string | - |
| updatedAt | yes | string | - |

### `UserDetail`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| email | yes | string | - |
| name | yes | string | - |
| status | yes | string | - |
| platformRoles | yes | array[PlatformRole] | - |
| platformPermissions | yes | array[string] | - |
| tenants | yes | array[UserTenantSummary] | - |
| currentSubscription | no | UserSubscriptionSummary \| null | - |
| orderSummary | no | UserOrderSummary | - |
| usageLifetime | no | UserLifetimeUsageSummary | - |
| createdAt | yes | string | - |
| updatedAt | yes | string | - |

### `UserLifetimeUsageSummary`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| startDate | no | string \| null | - |
| usageDays | no | integer | - |
| stopped | no | boolean | - |

### `UserOrderItem`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| orderNo | yes | string | - |
| planName | no | string \| null | - |
| billingPeriod | no | string \| null | - |
| amountCents | no | integer | - |
| paidAt | no | string \| null | - |
| status | yes | string | - |

### `UserOrderSummary`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| totalAmountCents | no | integer | - |
| orderCount | no | integer | - |
| recentOrders | no | array[UserOrderItem] | - |

### `UserSubscriptionSummary`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| subscriptionId | no | string \| null | - |
| planId | no | string \| null | - |
| planCode | no | string \| null | - |
| planName | no | string \| null | - |
| billingPeriod | no | string \| null | - |
| status | no | string \| null | - |
| currentPeriodStart | no | string \| null | - |
| currentPeriodEnd | no | string \| null | - |
| daysUntilExpiry | no | integer \| null | - |
| cancelAtPeriodEnd | no | boolean | - |
| autoRenew | no | boolean | - |
| priceLabel | no | string \| null | - |
| currentOrderNo | no | string \| null | - |
| paymentMethod | no | string \| null | - |
| tenantId | no | string \| null | - |
| tenantName | no | string \| null | - |

### `UserSummary`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| email | yes | string | - |
| name | yes | string | - |
| status | yes | string | - |
| platformRoles | yes | array[PlatformRole] | - |
| tenantCount | yes | integer | - |
| currentSubscription | no | UserSubscriptionSummary \| null | - |
| orderSummary | no | UserOrderSummary | - |
| usageLifetime | no | UserLifetimeUsageSummary | - |
| createdAt | yes | string | - |
| updatedAt | yes | string | - |

### `UserTenantSummary`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| id | yes | string | - |
| name | yes | string | - |
| type | yes | string | - |
| slug | yes | string | - |
| status | yes | string | - |
| role | yes | TenantRole | - |
| joinedAt | yes | string | - |

### `ValidationError`

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| loc | yes | array[string \| integer] | - |
| msg | yes | string | - |
| type | yes | string | - |
| input | no | {"title": "Input"} | - |
| ctx | no | object | - |
