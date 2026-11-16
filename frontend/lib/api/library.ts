import request, { requestData } from "../request";

export type LibraryFileType = "image" | "file";

export type LibraryFileLifecycle = "permanent" | "temporary";

export type LibrarySpaceType = "personal" | "team";

export type LibraryFileItem = {
  id: string;
  name: string;
  mimeType: string;
  type: LibraryFileType;
  sizeBytes: number;
  sizeLabel: string;
  updatedAt: string;
  createdAt: string;
  previewSupported: boolean;
  lifecycle?: LibraryFileLifecycle;
  spaceType?: LibrarySpaceType;
  ownerUserId?: string | null;
  ownerTenantId?: string | null;
  uploadedByUserId?: string | null;
  capabilities?: Record<string, boolean>;
};

export type LibraryFilesResponse = {
  items: LibraryFileItem[];
  total: number;
  page: number;
  pageSize: number;
};

export type LibraryFilesQuery = {
  keyword?: string;
  type?: "all" | LibraryFileType;
  lifecycle?: LibraryFileLifecycle;
  spaceType?: LibrarySpaceType;
  page?: number;
  pageSize?: number;
  sort?: "updatedAt_desc" | "updatedAt_asc" | "name_asc" | "name_desc" | "size_desc" | "size_asc";
};

export type LibraryPreviewResponse = {
  previewType: "text" | "url" | "unsupported";
  content?: string | null;
  url?: string | null;
  mimeType?: string | null;
  expiresAt?: string | null;
};

export type LibraryDownloadResponse = {
  method: "GET";
  downloadUrl: string;
  expiresAt: string;
};

export type DeleteLibraryFileResponse = {
  id: string;
  status: "deleted";
};

export type LibraryUploadUrlParams = {
  fileName: string;
  mimeType?: string;
  fileSizeBytes: number;
  contentHash?: string;
  spaceType?: LibrarySpaceType;
};

export type LibraryUploadUrlResponse = {
  uploadSessionId: string;
  fileId: string;
  method?: "PUT" | "POST";
  uploadUrl: string;
  headers?: Record<string, string>;
  objectKey: string;
  expiresAt: string;
  spaceType?: LibrarySpaceType;
};

export type CompleteLibraryUploadParams = {
  uploadSessionId: string;
  contentHash?: string;
  lifecycle?: LibraryFileLifecycle;
};

export type LibrarySpaceCapabilities = {
  list?: boolean;
  read?: boolean;
  upload?: boolean;
  rename?: boolean;
  delete?: boolean;
  promote?: boolean;
  useAgent?: boolean;
};

export type StorageCategory = {
  fileCount: number;
  fileBytes: number;
  imageCount: number;
  imageBytes: number;
};

export type LibrarySpace = {
  spaceType: LibrarySpaceType;
  status: "full" | "read_only" | "none";
  quotaBytes: number;
  usedBytes: number;
  reservedBytes: number;
  remainingBytes: number;
  capabilities: LibrarySpaceCapabilities;
  breakdown?: {
    permanent: StorageCategory;
    temporary: StorageCategory;
  };
};

export type LibrarySpacesResponse = {
  items: LibrarySpace[];
};

export function getLibrarySpaces() {
  return requestData(
    request.get<LibrarySpacesResponse>("/api/v1/library/spaces")
  );
}

export function getLibraryFiles(params: LibraryFilesQuery = {}) {
  return requestData(
    request.get<LibraryFilesResponse>("/api/v1/library/files", {
      params,
    })
  );
}

export function requestLibraryUploadUrl(data: LibraryUploadUrlParams) {
  return requestData(
    request.post<LibraryUploadUrlResponse>(
      "/api/v1/library/files/upload-url",
      data
    )
  );
}

export async function uploadFileToStorage(
  file: File,
  upload: LibraryUploadUrlResponse
) {
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
}

export function completeLibraryUpload(data: CompleteLibraryUploadParams) {
  return requestData(
    request.post<LibraryFileItem>("/api/v1/library/files/complete-upload", data)
  );
}

export async function uploadLibraryFile(
  file: File,
  spaceType: LibrarySpaceType = "personal",
) {
  const upload = await requestLibraryUploadUrl({
    fileName: file.name,
    mimeType: file.type || "application/octet-stream",
    fileSizeBytes: file.size,
    spaceType,
  });

  await uploadFileToStorage(file, upload);

  return completeLibraryUpload({
    uploadSessionId: upload.uploadSessionId,
  });
}

// Upload a file as a temporary chat attachment. The completed file is created
// unbound (no session) so it can be uploaded before a session exists; the first
// chat turn that references its id binds it to that session. Temporary files are
// retention-limited by the backend (see LIBRARY_FILE_LIFECYCLE docs).
export async function uploadChatAttachment(file: File) {
  const upload = await requestLibraryUploadUrl({
    fileName: file.name,
    mimeType: file.type || "application/octet-stream",
    fileSizeBytes: file.size,
  });

  await uploadFileToStorage(file, upload);

  return completeLibraryUpload({
    uploadSessionId: upload.uploadSessionId,
    lifecycle: "temporary",
  });
}

// Flip a temporary chat attachment into a permanent library file in place (no byte copy).
// After promotion it leaves the temporary list and appears in the default permanent list.
// Backend returns 409 LIBRARY_FILE_NOT_PROMOTABLE if it already expired / is permanent / deleted.
export function promoteLibraryFile(fileId: string) {
  return requestData(
    request.post<LibraryFileItem>(
      `/api/v1/library/files/${encodeURIComponent(fileId)}/promote`
    )
  );
}

export function getLibraryFilePreview(fileId: string) {
  return requestData(
    request.get<LibraryPreviewResponse>(
      `/api/v1/library/files/${encodeURIComponent(fileId)}/preview`
    )
  );
}

export function getLibraryFileDownload(fileId: string) {
  return requestData(
    request.get<LibraryDownloadResponse>(
      `/api/v1/library/files/${encodeURIComponent(fileId)}/download`
    )
  );
}

export function deleteLibraryFile(fileId: string) {
  return requestData(
    request.delete<DeleteLibraryFileResponse>(
      `/api/v1/library/files/${encodeURIComponent(fileId)}`
    )
  );
}
