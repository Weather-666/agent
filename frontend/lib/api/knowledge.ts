import request, { getAccessToken, requestData } from "../request";

export type KnowledgeBase = {
  id: string;
  ownerUserId: string | null;
  ownerUserName: string | null;
  name: string;
  description: string | null;
  status: "active" | "archived";
  indexStatus: "provisioning" | "ready" | "failed" | "deleting";
  indexError: string | null;
  indexWorkspace: string | null;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
};

export type KnowledgeBasesResponse = {
  items: KnowledgeBase[];
};

export type KnowledgeBaseStatusFilter = "active" | "archived" | "all";

export type CreateKnowledgeBaseParams = {
  name: string;
  description?: string;
  metadata?: Record<string, unknown>;
};

export type UpdateKnowledgeBaseParams = Partial<CreateKnowledgeBaseParams>;

export type KnowledgeBaseDocument = {
  id: string;
  knowledgeBaseId: string;
  fileName: string;
  fileType: "pdf" | "docx" | "pptx" | "xlsx" | "md" | "txt" | "html" | "csv" | "json";
  mimeType: string | null;
  storageKey: string;
  contentHash: string | null;
  sourceSha: string | null;
  indexedSha: string | null;
  indexDocumentId: string | null;
  indexPipelineVersion: string | null;
  fileSizeBytes: number;
  parseStatus: "pending" | "processing" | "ready" | "failed";
  indexStatus: "pending" | "processing" | "ready" | "failed" | "stale";
  parseError: string | null;
  lastError: string | null;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
};

export type KnowledgeIndexReview = {
  knowledgeBaseId: string;
  status: "not_required" | "pending_parse" | "review_required" | "approved";
  thresholdBytes: number;
  documentCount: number;
  totalSizeBytes: number;
  batchToken?: string | null;
  documents: Array<{
    documentId: string;
    fileName: string;
    fileSizeBytes: number;
  }>;
};

export type KnowledgeBaseDocumentsResponse = {
  items: KnowledgeBaseDocument[];
};

export type DocumentUploadUrlParams = {
  fileName: string;
  mimeType?: string;
  fileSizeBytes: number;
  contentHash?: string;
};

export type DocumentUploadUrlResponse = {
  uploadSessionId: string;
  documentId: string;
  method: "PUT";
  uploadUrl: string;
  headers: Record<string, string>;
  objectKey: string;
  expiresAt: string;
};

export type DocumentUploadUrlsParams = {
  files: DocumentUploadUrlParams[];
};

export type DocumentUploadUrlsResponse = {
  items: DocumentUploadUrlResult[];
};

export type BatchItemError = {
  code: string;
  message: string;
  details?: Record<string, unknown>;
};

export type DocumentUploadUrlResult = {
  fileName: string;
  status: "created" | "failed";
  upload?: DocumentUploadUrlResponse | null;
  error?: BatchItemError | null;
};

export type CompleteDocumentUploadParams = {
  uploadSessionId: string;
  etag?: string;
  fileSizeBytes: number;
};

export type CompleteDocumentUploadsParams = {
  items: CompleteDocumentUploadParams[];
};

export type CompleteDocumentUploadsResponse = {
  items: CompleteDocumentUploadResult[];
};

export type CompleteDocumentUploadResult = {
  uploadSessionId: string;
  status: "completed" | "failed";
  document?: KnowledgeBaseDocument | null;
  error?: BatchItemError | null;
};

export type KnowledgeBaseUploadFailure = {
  fileName: string;
  code: string;
  message: string;
  details?: Record<string, unknown>;
};

export type KnowledgeBaseUploadResult = {
  documents: KnowledgeBaseDocument[];
  failures: KnowledgeBaseUploadFailure[];
};

export type DocumentDownloadUrlResponse = {
  method: "GET";
  downloadUrl: string;
  expiresAt: string;
};

const KNOWLEDGE_BASES_CACHE_TTL = 5 * 60 * 1000;

let knowledgeBasesCache:
  | {
      expiresAt: number;
      data: KnowledgeBasesResponse;
    }
  | null = null;
let knowledgeBasesRequest: Promise<KnowledgeBasesResponse> | null = null;

export function getKnowledgeBases(status: KnowledgeBaseStatusFilter = "active", _client: typeof request = request) {
  const accessToken = getAccessToken();

  return requestData(
    _client.get<KnowledgeBasesResponse>("/api/v1/knowledge-bases", {
      params: { status },
      headers: {
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
    })
  );
}

export function getKnowledgeBase(knowledgeBaseId: string, _client: typeof request = request) {
  const accessToken = getAccessToken();

  return requestData(
    _client.get<KnowledgeBase>(`/api/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}`, {
      headers: {
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
    })
  );
}

export function createKnowledgeBase(data: CreateKnowledgeBaseParams, _client: typeof request = request) {
  const accessToken = getAccessToken();

  return requestData(
    _client.post<KnowledgeBase>("/api/v1/knowledge-bases", data, {
      headers: {
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
    })
  ).then((knowledgeBase) => {
    clearKnowledgeBasesCache();
    return knowledgeBase;
  });
}

export function updateKnowledgeBase(knowledgeBaseId: string, data: UpdateKnowledgeBaseParams, _client: typeof request = request) {
  const accessToken = getAccessToken();

  return requestData(
    _client.patch<KnowledgeBase>(`/api/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}`, data, {
      headers: {
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
    })
  ).then((knowledgeBase) => {
    clearKnowledgeBasesCache();
    return knowledgeBase;
  });
}

export function archiveKnowledgeBase(knowledgeBaseId: string, _client: typeof request = request) {
  const accessToken = getAccessToken();

  return requestData(
    _client.post<KnowledgeBase>(
      `/api/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/archive`,
      undefined,
      {
        headers: {
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
      }
    )
  ).then((knowledgeBase) => {
    clearKnowledgeBasesCache();
    return knowledgeBase;
  });
}

export function getKnowledgeIndexReview(knowledgeBaseId: string, _client: typeof request = request) {
  const accessToken = getAccessToken();

  return requestData(
    _client.get<KnowledgeIndexReview>(
      `/api/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/index-review`,
      {
        headers: {
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
      }
    )
  );
}

export function approveKnowledgeIndexReview(knowledgeBaseId: string, batchToken: string, _client: typeof request = request) {
  const accessToken = getAccessToken();

  return requestData(
    _client.post<KnowledgeIndexReview>(
      `/api/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/index-review/approve`,
      { batchToken },
      {
        headers: {
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
      }
    )
  );
}

export function activateKnowledgeBase(knowledgeBaseId: string, _client: typeof request = request) {
  const accessToken = getAccessToken();

  return requestData(
    _client.post<KnowledgeBase>(
      `/api/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/activate`,
      undefined,
      {
        headers: {
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
      }
    )
  ).then((knowledgeBase) => {
    clearKnowledgeBasesCache();
    return knowledgeBase;
  });
}

export function deleteKnowledgeBase(knowledgeBaseId: string, _client: typeof request = request) {
  const accessToken = getAccessToken();

  return requestData(
    _client.delete<void>(`/api/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}`, {
      headers: {
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
    })
  ).then((result) => {
    clearKnowledgeBasesCache();
    return result;
  });
}

export function clearKnowledgeBasesCache() {
  knowledgeBasesCache = null;
  knowledgeBasesRequest = null;
}

export function getKnowledgeBasesCached() {
  const now = Date.now();

  if (knowledgeBasesCache && knowledgeBasesCache.expiresAt > now) {
    return Promise.resolve(knowledgeBasesCache.data);
  }

  knowledgeBasesRequest ??= getKnowledgeBases()
    .then((data) => {
      knowledgeBasesCache = {
        data,
        expiresAt: Date.now() + KNOWLEDGE_BASES_CACHE_TTL,
      };

      return data;
    })
    .finally(() => {
      knowledgeBasesRequest = null;
    });

  return knowledgeBasesRequest;
}

export function getKnowledgeBaseDocuments(
  knowledgeBaseId: string,
  params: { limit?: number; offset?: number } = {},
  _client: typeof request = request
) {
  const accessToken = getAccessToken();
  const searchParams = new URLSearchParams();

  if (typeof params.limit === "number") searchParams.set("limit", String(params.limit));
  if (typeof params.offset === "number") searchParams.set("offset", String(params.offset));

  const queryString = searchParams.toString();
  const url = `/api/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/documents${queryString ? `?${queryString}` : ""}`;

  return requestData(
    _client.get<KnowledgeBaseDocumentsResponse>(url, {
      headers: {
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
    })
  );
}

export function requestDocumentUploadUrl(knowledgeBaseId: string, data: DocumentUploadUrlParams, _client: typeof request = request) {
  const accessToken = getAccessToken();

  return requestData(
    _client.post<DocumentUploadUrlResponse>(
      `/api/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/documents/upload-url`,
      data,
      {
        headers: {
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
      }
    )
  );
}

export function requestDocumentUploadUrls(knowledgeBaseId: string, data: DocumentUploadUrlsParams, _client: typeof request = request) {
  const accessToken = getAccessToken();

  return requestData(
    _client.post<DocumentUploadUrlsResponse>(
      `/api/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/documents/upload-urls`,
      data,
      {
        headers: {
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
      }
    )
  );
}

export async function uploadDocumentToStorage(file: File, upload: DocumentUploadUrlResponse) {
  const method = (upload.method ?? "PUT").toUpperCase();
  if (method === "GET" || method === "HEAD") {
    throw new Error("文件上传地址方法异常，请稍后重试");
  }

  const response = await fetch(upload.uploadUrl, {
    method,
    headers: upload.headers,
    body: file,
  });

  if (!response.ok) {
    throw new Error(`文件直传失败：${response.status}`);
  }

  return response.headers.get("etag")?.replace(/^"|"$/g, "") ?? "";
}

export function completeDocumentUpload(knowledgeBaseId: string, data: CompleteDocumentUploadParams, _client: typeof request = request) {
  const accessToken = getAccessToken();

  return requestData(
    _client.post<KnowledgeBaseDocument>(
      `/api/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/documents/complete-upload`,
      data,
      {
        headers: {
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
      }
    )
  );
}

export function completeDocumentUploads(knowledgeBaseId: string, data: CompleteDocumentUploadsParams, _client: typeof request = request) {
  const accessToken = getAccessToken();

  return requestData(
    _client.post<CompleteDocumentUploadsResponse>(
      `/api/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/documents/complete-uploads`,
      data,
      {
        headers: {
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
      }
    )
  );
}

export async function uploadKnowledgeBaseDocument(knowledgeBaseId: string, file: File, _client: typeof request = request) {
  const upload = await requestDocumentUploadUrl(knowledgeBaseId, {
    fileName: file.name,
    mimeType: file.type || "application/octet-stream",
    fileSizeBytes: file.size,
  }, _client);
  const etag = await uploadDocumentToStorage(file, upload);

  return completeDocumentUpload(knowledgeBaseId, {
    uploadSessionId: upload.uploadSessionId,
    etag,
    fileSizeBytes: file.size,
  }, _client);
}

export async function uploadKnowledgeBaseDocuments(knowledgeBaseId: string, files: File[], _client: typeof request = request) {
  if (!files.length) return { documents: [], failures: [] } satisfies KnowledgeBaseUploadResult;

  const uploads = await requestDocumentUploadUrls(knowledgeBaseId, {
    files: files.map((file) => ({
      fileName: file.name,
      mimeType: file.type || "application/octet-stream",
      fileSizeBytes: file.size,
    })),
  }, _client);

  const failures: KnowledgeBaseUploadFailure[] = [];
  const created = uploads.items.flatMap((item, index) => {
    const file = files[index];
    const upload = item.upload;
    if (item.status !== "created" || !file || !upload) {
      failures.push({
        fileName: item.fileName || file?.name || "-",
        code: item.error?.code || "UPLOAD_URL_FAILED",
        message: item.error?.message || "Failed to create an upload URL",
        details: item.error?.details,
      });
      return [];
    }
    return [{ file, upload }];
  });

  const storedResults = await Promise.all(
    created.map(async ({ file, upload }) => {
      try {
        const etag = await uploadDocumentToStorage(file, upload);
        return { file, upload, etag };
      } catch (error) {
        failures.push({
          fileName: file.name,
          code: "OBJECT_UPLOAD_FAILED",
          message: error instanceof Error ? error.message : "Failed to upload the object",
        });
        return null;
      }
    })
  );
  const stored = storedResults.filter((item): item is NonNullable<typeof item> => item !== null);
  if (!stored.length) return { documents: [], failures };

  const completed = await completeDocumentUploads(knowledgeBaseId, {
    items: stored.map(({ file, upload, etag }) => ({
      uploadSessionId: upload.uploadSessionId,
      etag,
      fileSizeBytes: file.size,
    })),
  }, _client);
  const completedBySession = new Map(
    completed.items.map((item) => [item.uploadSessionId, item] as const)
  );
  const documents: KnowledgeBaseDocument[] = [];
  for (const { file, upload } of stored) {
    const item = completedBySession.get(upload.uploadSessionId);
    if (item?.status === "completed" && item.document) {
      documents.push(item.document);
      continue;
    }
    failures.push({
      fileName: file.name,
      code: item?.error?.code || "UPLOAD_COMPLETION_FAILED",
      message: item?.error?.message || "Failed to complete the upload",
      details: item?.error?.details,
    });
  }

  return { documents, failures } satisfies KnowledgeBaseUploadResult;
}

export function deleteKnowledgeBaseDocument(knowledgeBaseId: string, documentId: string, _client: typeof request = request) {
  const accessToken = getAccessToken();

  return requestData(
    _client.delete<void>(
      `/api/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/documents/${encodeURIComponent(documentId)}`,
      {
        headers: {
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
      }
    )
  );
}

export function getKnowledgeBaseDocumentDownloadUrl(knowledgeBaseId: string, documentId: string, _client: typeof request = request) {
  const accessToken = getAccessToken();

  return requestData(
    _client.get<DocumentDownloadUrlResponse>(
      `/api/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/documents/${encodeURIComponent(documentId)}/download-url`,
      {
        headers: {
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
      }
    )
  );
}
