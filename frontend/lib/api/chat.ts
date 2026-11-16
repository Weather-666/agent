import request, { apiUrl, getAccessToken, getTenantId, requestData } from "../request";

export const CHAT_SESSIONS_CHANGED_EVENT = "winwise:chat-sessions-changed";

export const CHAT_SESSION_TITLE_HINT_EVENT = "winwise:chat-session-title-hint";

export type ChatSessionTitleHint = {
  sessionId: string;
  title: string;
};

// Optimistically show a title for a session before the server has one -- a brand-new chat, or the
// window while the backend's auto-generated title is still pending. app-shell applies it to the
// sidebar and keeps it only until the server returns a real (non-empty) title.
export function dispatchChatSessionTitleHint(sessionId: string, title: string) {
  if (typeof window === "undefined" || !sessionId || !title) return;
  window.dispatchEvent(
    new CustomEvent<ChatSessionTitleHint>(CHAT_SESSION_TITLE_HINT_EVENT, {
      detail: { sessionId, title },
    })
  );
}

export type ChatSession = {
  id?: string | number;
  sessionId?: string | number;
  chatId?: string | number;
  title?: string;
  name?: string;
  summary?: string;
  knowledgeBaseIds?: string[];
  expertId?: string | null;
  runtimeType?: string | null;
  status?: string;
  isPinned?: boolean;
  createdAt?: string;
  updatedAt?: string;
  lastMessageAt?: string;
};

export type ChatSessionsResponse =
  | ChatSession[]
  | {
      data?: ChatSession[] | { records?: ChatSession[]; items?: ChatSession[]; sessions?: ChatSession[] };
      records?: ChatSession[];
      items?: ChatSession[];
      sessions?: ChatSession[];
    };

export type CreateChatSessionParams = {
  title?: string;
  expertId?: string;
  runtimeType?: string;
  knowledgeBaseIds?: string[];
};

export type RenameChatSessionParams = {
  title: string;
};

export type PinChatSessionParams = {
  isPinned: boolean;
};

export type ArchiveChatSessionParams = {
  archived: boolean;
};

export type CreateChatSessionResponse =
  | ChatSession
  | {
      data: ChatSession;
      success?: boolean;
    };

// Provenance snapshot the backend stores on a turn for each referenced attachment.
export type ChatTurnAttachment = {
  fileId?: string;
  name?: string;
  mimeType?: string;
  sizeBytes?: number;
  sizeLabel?: string;
  lifecycle?: string;
  spaceType?: string;
  attachedAt?: string;
  // Personal library tool read: source="personal_library_tool", readAt is ISO timestamp
  source?: string;
  readAt?: string;
};

export type CreateChatTurnParams = {
  sessionId: string;
  question: string;
  webSearchEnabled?: boolean;
  // Completed library_files ids referenced by this turn. These are plain file ids,
  // never URLs — the backend resolves each id to its stored object and reads the
  // content. Two sources feed this field and the backend MUST accept both:
  //   - temporary attachments freshly uploaded in the composer (lifecycle=temporary),
  //   - permanent library files picked via the "@" mention menu (lifecycle=permanent).
  // Contract: resolution must be lifecycle-agnostic. Do not gate on lifecycle or
  // assume every id is an unbound temporary file (e.g. a "bind to session on first
  // turn" step must be a no-op for already-permanent files, not a rejection).
  attachmentFileIds?: string[];
  knowledgeBaseIds?: string[];
  llmModel?: string;
  queryRewrite?: boolean;
  multiHop?: {
    enabled?: boolean;
    [key: string]: unknown;
  };
};

export type ChatTurnResponse = {
  turnId: string;
  status: string;
  priority?: string;
  queuePosition?: {
    position?: number;
    queueDepth?: number;
  };
};

export type ChatSessionMessage = {
  id?: string | number;
  turnId?: string;
  messageId?: string | number;
  sessionId?: string | number;
  role?: string;
  sender?: string;
  senderType?: string;
  sender_type?: string;
  content?: string;
  text?: string;
  requestText?: string;
  request_text?: string;
  responseText?: string;
  response_text?: string;
  reasoningText?: string;
  reasoning_text?: string;
  status?: string;
  stopReason?: string | null;
  stop_reason?: string | null;
  errorMessage?: string | null;
  error_message?: string | null;
  eventSeq?: number;
  citations?: unknown[];
  events?: unknown[];
  traceEvents?: unknown[];
  trace_events?: unknown[];
  traces?: unknown[];
  trace?: unknown[];
  steps?: unknown[];
  reasoning?: unknown;
  metadata?: {
    events?: unknown[];
    traceEvents?: unknown[];
    trace_events?: unknown[];
    traces?: unknown[];
    trace?: unknown[];
    steps?: unknown[];
  } & Record<string, unknown>;
  attachments?: ChatTurnAttachment[];
  createdAt?: string;
  created_at?: string;
  completedAt?: string | null;
  completed_at?: string | null;
};

export type ChatSessionMessagesResponse =
  | ChatSessionMessage[]
  | {
      data?: ChatSessionMessage[] | { records?: ChatSessionMessage[]; items?: ChatSessionMessage[]; messages?: ChatSessionMessage[] };
      records?: ChatSessionMessage[];
      items?: ChatSessionMessage[];
      messages?: ChatSessionMessage[];
    };

export function getChatSessions(params: { status?: "active" | "archived" } = {}) {
  const accessToken = getAccessToken();
  const tenantId = getTenantId();

  return requestData(
    request.get<ChatSessionsResponse>("/api/v1/chat/sessions", {
      params,
      headers: {
        "X-Tenant-ID": tenantId,
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
    })
  );
}

export function createChatSession(data: CreateChatSessionParams = {}) {
  const accessToken = getAccessToken();
  const tenantId = getTenantId();

  return requestData(
    request.post<CreateChatSessionResponse>("/api/v1/chat/sessions", data, {
      headers: {
        "X-Tenant-ID": tenantId,
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
    })
  );
}

export function getChatSession(sessionId: string) {
  const accessToken = getAccessToken();
  const tenantId = getTenantId();

  return requestData(
    request.get<ChatSession>(`/api/v1/chat/sessions/${encodeURIComponent(sessionId)}`, {
      headers: {
        "X-Tenant-ID": tenantId,
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
    })
  );
}

export function renameChatSession(sessionId: string, data: RenameChatSessionParams) {
  const accessToken = getAccessToken();
  const tenantId = getTenantId();

  return requestData(
    request.patch<ChatSession>(
      `/api/v1/chat/sessions/${encodeURIComponent(sessionId)}/title`,
      data,
      {
        headers: {
          "X-Tenant-ID": tenantId,
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
      }
    )
  );
}

export function setChatSessionPinned(sessionId: string, data: PinChatSessionParams) {
  const accessToken = getAccessToken();
  const tenantId = getTenantId();

  return requestData(
    request.patch<ChatSession>(
      `/api/v1/chat/sessions/${encodeURIComponent(sessionId)}/pin`,
      data,
      {
        headers: {
          "X-Tenant-ID": tenantId,
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
      }
    )
  );
}

export function setChatSessionArchived(sessionId: string, data: ArchiveChatSessionParams) {
  const accessToken = getAccessToken();
  const tenantId = getTenantId();

  return requestData(
    request.patch<ChatSession>(
      `/api/v1/chat/sessions/${encodeURIComponent(sessionId)}/archive`,
      data,
      {
        headers: {
          "X-Tenant-ID": tenantId,
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
      }
    )
  );
}

export function deleteChatSession(sessionId: string) {
  const accessToken = getAccessToken();
  const tenantId = getTenantId();

  return requestData(
    request.delete<{ id: string; status: string }>(
      `/api/v1/chat/sessions/${encodeURIComponent(sessionId)}`,
      {
        headers: {
          "X-Tenant-ID": tenantId,
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
      }
    )
  );
}

export function getChatSessionMessages(sessionId: string) {
  const accessToken = getAccessToken();
  const tenantId = getTenantId();

  return requestData(
    request.get<ChatSessionMessagesResponse>(
      `/api/v1/chat/sessions/${encodeURIComponent(sessionId)}/messages`,
      {
        headers: {
          "X-Tenant-ID": tenantId,
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
      }
    )
  );
}

export type ChatSearchScope = "all" | "question" | "answer";

export type ChatSearchParams = {
  keyword: string;
  scope?: ChatSearchScope;
  limit?: number;
  offset?: number;
};

export type ChatSearchResultItem = {
  sessionId: string;
  title: string | null;
  matchedTurnId: string;
  matchedType: "title" | "question" | "answer";
  snippet: string;
};

export type ChatSearchResponse = {
  items: ChatSearchResultItem[];
  total: number;
  limit: number;
  offset: number;
};

export function searchChatSessions(params: ChatSearchParams) {
  const accessToken = getAccessToken();
  const tenantId = getTenantId();

  return requestData(
    request.get<ChatSearchResponse>("/api/v1/chat/search", {
      params,
      headers: {
        "X-Tenant-ID": tenantId,
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
    })
  );
}

export type SubmitChatPermissionParams = { optionId?: string; outcome?: "cancelled" };

export function submitChatPermission(permissionId: string, data: SubmitChatPermissionParams) {
  const accessToken = getAccessToken();
  const tenantId = getTenantId();

  return requestData(
    request.post<void>(
      `/api/v1/chat/permissions/${encodeURIComponent(permissionId)}`,
      data,
      {
        headers: {
          "X-Tenant-ID": tenantId,
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
      }
    )
  );
}

export function cancelChatTurn(turnId: string) {
  const accessToken = getAccessToken();
  const tenantId = getTenantId();

  return requestData(
    request.post<ChatTurnResponse>(
      `/api/v1/chat/turns/${encodeURIComponent(turnId)}/cancel`,
      undefined,
      {
        headers: {
          "X-Tenant-ID": tenantId,
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
      }
    )
  );
}

// These URLs are consumed by raw `fetch`/`EventSource` (SSE streaming), not axios,
// so prepend the API base via apiUrl() to match the axios baseURL / Next.js basePath.
export function getCreateChatTurnUrl(sessionId: string) {
  return apiUrl(`/api/v1/chat/sessions/${encodeURIComponent(sessionId)}/turns`);
}

export function getChatTurnEventsUrl(turnId: string, after?: number) {
  const query = typeof after === "number" ? `?after=${encodeURIComponent(after)}` : "";
  return apiUrl(`/api/v1/chat/turns/${encodeURIComponent(turnId)}/events${query}`);
}
