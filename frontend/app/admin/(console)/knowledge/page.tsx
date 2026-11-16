"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  App,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  type TableColumnsType,
} from "antd";
import { PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { useI18n } from "@/lib/i18n";
import {
  activateKnowledgeBase,
  approveKnowledgeIndexReview,
  archiveKnowledgeBase,
  createKnowledgeBase,
  deleteKnowledgeBase,
  deleteKnowledgeBaseDocument,
  getKnowledgeBaseDocumentDownloadUrl,
  getKnowledgeBaseDocuments,
  getKnowledgeBases,
  getKnowledgeIndexReview,
  updateKnowledgeBase,
  uploadKnowledgeBaseDocuments,
  type KnowledgeBaseUploadFailure,
  type KnowledgeIndexReview,
  type KnowledgeBaseDocument,
  type KnowledgeBase,
} from "@/lib/api/admin-client";

import {
  DOCUMENT_PAGE_SIZE,
  formatDate,
  formatFileSize,
  getErrorMessage,
  knowledgeStatusTag,
  unwrapDocuments,
  type CreateFormValues,
  type EditFormValues,
} from "./_helpers";

const { Title, Text } = Typography;

type LoadDocumentsOptions = {
  showLoading?: boolean;
  notifyOnError?: boolean;
};

type LoadKnowledgeBasesOptions = {
  showLoading?: boolean;
  notifyOnError?: boolean;
};

export default function AdminKnowledgePage() {
  const { t } = useI18n();
  const { message, modal } = App.useApp();
  const [createForm] = Form.useForm<CreateFormValues>();
  const [editForm] = Form.useForm<EditFormValues>();
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [documents, setDocuments] = useState<KnowledgeBaseDocument[]>([]);
  const [knowledgeKeyword, setKnowledgeKeyword] = useState("");
  const [documentKeyword, setDocumentKeyword] = useState("");
  const [isKnowledgeLoading, setIsKnowledgeLoading] = useState(true);
  const [isDocumentLoading, setIsDocumentLoading] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [switchingStatusId, setSwitchingStatusId] = useState("");
  const [deletingKnowledgeBaseId, setDeletingKnowledgeBaseId] = useState("");
  const [deletingDocumentId, setDeletingDocumentId] = useState("");
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [indexReview, setIndexReview] = useState<KnowledgeIndexReview | null>(null);
  const [isRebuildingIndex, setIsRebuildingIndex] = useState(false);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [editingKnowledgeBase, setEditingKnowledgeBase] = useState<KnowledgeBase | null>(null);
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const documentRequestSeqRef = useRef(0);
  const documentLoadingSeqRef = useRef(0);
  const pollInFlightRef = useRef(false);

  const loadIndexReview = useCallback((knowledgeBaseId: string) => {
    return getKnowledgeIndexReview(knowledgeBaseId)
      .then((response) => {
        setIndexReview(response);
      })
      .catch(() => {
        setIndexReview(null);
      });
  }, []);

  const loadKnowledgeBases = useCallback((options: LoadKnowledgeBasesOptions = {}) => {
    const { showLoading = true, notifyOnError = true } = options;
    if (showLoading) setIsKnowledgeLoading(true);

    return getKnowledgeBases("all")
      .then((response) => {
        const items = Array.isArray(response.items) ? response.items : [];
        setKnowledgeBases(items);
        setSelectedKnowledgeBaseId((current) => current || items[0]?.id || "");
      })
      .catch((err) => {
        if (notifyOnError) {
          message.error(getErrorMessage(err, t("adminKnowledge.loadKnowledgeBasesError")));
        }
      })
      .finally(() => {
        if (showLoading) setIsKnowledgeLoading(false);
      });
  }, [t, message]);

  const loadDocuments = useCallback((knowledgeBaseId: string, options: LoadDocumentsOptions = {}) => {
    const { showLoading = true, notifyOnError = true } = options;
    const requestSeq = documentRequestSeqRef.current + 1;
    documentRequestSeqRef.current = requestSeq;
    const loadingSeq = showLoading ? documentLoadingSeqRef.current + 1 : 0;
    if (showLoading) {
      documentLoadingSeqRef.current = loadingSeq;
      setIsDocumentLoading(true);
    }

    return getKnowledgeBaseDocuments(knowledgeBaseId, {
      limit: DOCUMENT_PAGE_SIZE,
      offset: 0,
    })
      .then((response) => {
        if (documentRequestSeqRef.current !== requestSeq) return;
        setDocuments(unwrapDocuments(response));
      })
      .catch((err) => {
        if (documentRequestSeqRef.current !== requestSeq) return;
        setDocuments([]);
        if (notifyOnError) {
          message.error(getErrorMessage(err, t("adminKnowledge.loadDocumentsError")));
        }
      })
      .finally(() => {
        if (showLoading && documentLoadingSeqRef.current === loadingSeq) {
          setIsDocumentLoading(false);
        }
      });
  }, [t, message]);

  useEffect(() => {
    let ignore = false;
    queueMicrotask(() => {
      if (!ignore) void loadKnowledgeBases();
    });

    return () => {
      ignore = true;
    };
  }, [loadKnowledgeBases]);

  useEffect(() => {
    if (!selectedKnowledgeBaseId) return;

    let ignore = false;
    queueMicrotask(() => {
      if (!ignore) void loadDocuments(selectedKnowledgeBaseId);
      if (!ignore) void loadIndexReview(selectedKnowledgeBaseId);
    });

    return () => {
      ignore = true;
      documentRequestSeqRef.current += 1;
    };
  }, [loadDocuments, loadIndexReview, selectedKnowledgeBaseId]);

  const hasActiveDocumentWork = documents.some(
    (document) =>
      document.parseStatus === "pending" ||
      document.parseStatus === "processing" ||
      document.indexStatus === "pending" ||
      document.indexStatus === "processing"
  );
  const selectedKnowledgeBaseIndexStatus = knowledgeBases.find(
    (item) => item.id === selectedKnowledgeBaseId
  )?.indexStatus;
  const hasActiveKnowledgeBaseWork =
    selectedKnowledgeBaseIndexStatus === "provisioning" ||
    selectedKnowledgeBaseIndexStatus === "deleting";

  // Parsing and indexing are independent asynchronous stages. Keep document states fresh while
  // either stage can still change.
  useEffect(() => {
    if (
      !selectedKnowledgeBaseId ||
      (!hasActiveDocumentWork &&
        !hasActiveKnowledgeBaseWork &&
        indexReview?.status !== "pending_parse")
    ) return;

    const timer = window.setInterval(() => {
      if (pollInFlightRef.current) return;
      pollInFlightRef.current = true;
      void Promise.all([
        loadKnowledgeBases({ showLoading: false, notifyOnError: false }),
        loadIndexReview(selectedKnowledgeBaseId),
        loadDocuments(selectedKnowledgeBaseId, { showLoading: false, notifyOnError: false }),
      ]).finally(() => {
        pollInFlightRef.current = false;
      });
    }, 5000);

    return () => {
      window.clearInterval(timer);
      pollInFlightRef.current = false;
    };
  }, [
    selectedKnowledgeBaseId,
    hasActiveDocumentWork,
    hasActiveKnowledgeBaseWork,
    indexReview?.status,
    loadKnowledgeBases,
    loadIndexReview,
    loadDocuments,
  ]);

  function openCreateModal() {
    createForm.setFieldsValue({ name: "", description: "" });
    setIsCreateModalOpen(true);
  }

  const handleCreateKnowledgeBase = async (values: CreateFormValues) => {
    setIsCreating(true);

    try {
      const created = await createKnowledgeBase({
        name: values.name.trim(),
        description: values.description.trim() || undefined,
        metadata: {},
      });

      setKnowledgeBases((prev) => [created, ...prev]);
      setSelectedKnowledgeBaseId((current) => current || created.id);
      setIsCreateModalOpen(false);
      message.success(t("adminKnowledge.createdNotice"));
    } catch (err) {
      message.error(getErrorMessage(err, t("adminKnowledge.createError")));
    } finally {
      setIsCreating(false);
    }
  };

  const handleDeleteKnowledgeBase = async (knowledgeBase: KnowledgeBase) => {
    const isSelected = selectedKnowledgeBaseId === knowledgeBase.id;
    setDeletingKnowledgeBaseId(knowledgeBase.id);

    try {
      await deleteKnowledgeBase(knowledgeBase.id);
      setKnowledgeBases((prev) => {
        const remaining = prev.filter((row) => row.id !== knowledgeBase.id);
        setSelectedKnowledgeBaseId((current) => {
          if (current !== knowledgeBase.id) return current;
          return remaining[0]?.id || "";
        });
        return remaining;
      });
      if (isSelected) {
        setDocuments([]);
        setSelectedFiles([]);
        setDocumentKeyword("");
      }
      message.success(t("adminKnowledge.deletedNotice"));
    } catch (err) {
      message.error(getErrorMessage(err, t("adminKnowledge.deleteError")));
    } finally {
      setDeletingKnowledgeBaseId("");
    }
  };

  const openEditModal = (knowledgeBase: KnowledgeBase) => {
    setEditingKnowledgeBase(knowledgeBase);
    editForm.setFieldsValue({ name: knowledgeBase.name, description: knowledgeBase.description ?? "" });
  };

  const handleUpdateKnowledgeBase = async (values: EditFormValues) => {
    if (!editingKnowledgeBase) return;

    setIsUpdating(true);

    try {
      const updated = await updateKnowledgeBase(editingKnowledgeBase.id, {
        name: values.name.trim(),
        description: values.description.trim() || undefined,
      });

      setKnowledgeBases((prev) => prev.map((row) => (row.id === updated.id ? updated : row)));
      setEditingKnowledgeBase(null);
      message.success(t("adminKnowledge.updatedNotice"));
    } catch (err) {
      message.error(getErrorMessage(err, t("adminKnowledge.updateError")));
    } finally {
      setIsUpdating(false);
    }
  };

  const handleSwitchKnowledgeStatus = async (knowledgeBase: KnowledgeBase) => {
    const isActive = knowledgeBase.status === "active";
    const nextStatus = isActive ? "archived" : "active";
    setSwitchingStatusId(knowledgeBase.id);

    try {
      // 停用走 archive、启用走 activate 专用接口（后端为这两个动作提供了独立端点，
      // 而不是通用的 PATCH status）。
      const updated = isActive
        ? await archiveKnowledgeBase(knowledgeBase.id)
        : await activateKnowledgeBase(knowledgeBase.id);
      if (updated.status !== nextStatus) {
        message.error(t("adminKnowledge.statusUpdateNoResponse"));
        return;
      }
      setKnowledgeBases((prev) => prev.map((row) => (row.id === updated.id ? updated : row)));
      message.success(isActive ? t("adminKnowledge.disabledNotice") : t("adminKnowledge.enabledNotice"));
    } catch (err) {
      message.error(getErrorMessage(err, t("adminKnowledge.switchStatusError")));
    } finally {
      setSwitchingStatusId("");
    }
  };

  const handleUploadDocument = async (filesToUpload?: File[]) => {
    const files = filesToUpload ?? selectedFiles;

    if (!selectedKnowledgeBaseId) {
      message.error(t("adminKnowledge.selectKnowledgeBaseFirst"));
      return;
    }
    if (!files.length) {
      message.error(t("adminKnowledge.selectDocumentToUpload"));
      return;
    }

    setIsUploading(true);

    try {
      const { documents: uploaded, failures } = await uploadKnowledgeBaseDocuments(
        selectedKnowledgeBaseId,
        files
      );
      setSelectedFiles([]);
      if (uploadInputRef.current) uploadInputRef.current.value = "";
      if (uploaded.length) {
        message.success(
          uploaded.length > 1
            ? t("adminKnowledge.uploadedCountNotice", { count: uploaded.length })
            : t("adminKnowledge.uploadSuccessNotice")
        );
      }
      if (failures.length) {
        message.warning(
          t("adminKnowledge.uploadPartialNotice", {
            success: uploaded.length,
            failed: failures.length,
            details: failures.map(formatUploadFailure).join("；"),
          }),
          8
        );
      }
      // 上传成功后从服务端重新拉取文档列表，确保状态、解析进度等字段与后端一致。
      await loadDocuments(selectedKnowledgeBaseId);
      await loadIndexReview(selectedKnowledgeBaseId);
    } catch (err) {
      message.error(getErrorMessage(err, t("adminKnowledge.uploadError")));
    } finally {
      setIsUploading(false);
    }
  };

  const handleDeleteDocument = async (document: KnowledgeBaseDocument) => {
    if (!selectedKnowledgeBaseId) return;
    setDeletingDocumentId(document.id);

    try {
      await deleteKnowledgeBaseDocument(selectedKnowledgeBaseId, document.id);
      setDocuments((prev) => prev.filter((item) => item.id !== document.id));
      message.success(t("adminKnowledge.documentDeletedNotice"));
    } catch (err) {
      message.error(getErrorMessage(err, t("adminKnowledge.deleteDocumentError")));
    } finally {
      setDeletingDocumentId("");
    }
  };

  const handleRebuildIndex = async () => {
    if (!selectedKnowledgeBaseId || !indexReview?.batchToken) return;
    setIsRebuildingIndex(true);

    try {
      await approveKnowledgeIndexReview(selectedKnowledgeBaseId, indexReview.batchToken);
      message.success(t("adminKnowledge.indexRebuildNotice"));
      await loadIndexReview(selectedKnowledgeBaseId);
      await loadDocuments(selectedKnowledgeBaseId);
    } catch (err) {
      message.error(getErrorMessage(err, t("adminKnowledge.indexRebuildError")));
    } finally {
      setIsRebuildingIndex(false);
    }
  };

  function confirmRebuildIndex() {
    if (indexReview?.status !== "review_required" || !indexReview.batchToken) return;
    modal.confirm({
      title: t("adminKnowledge.confirmRebuildIndexTitle"),
      content: t("adminKnowledge.confirmRebuildIndexMessage", {
        count: indexReview.documentCount,
        size: formatFileSize(indexReview.totalSizeBytes),
      }),
      okText: t("adminKnowledge.confirmRebuildIndexConfirm"),
      cancelText: t("adminKnowledge.confirmDeleteCancel"),
      onOk: handleRebuildIndex,
    });
  }

  const handleDownloadDocument = async (document: KnowledgeBaseDocument) => {
    if (!selectedKnowledgeBaseId) return;

    try {
      const response = await getKnowledgeBaseDocumentDownloadUrl(selectedKnowledgeBaseId, document.id);
      window.open(response.downloadUrl, "_blank", "noopener,noreferrer");
    } catch (err) {
      message.error(getErrorMessage(err, t("adminKnowledge.downloadUrlError")));
    }
  };

  function confirmDeleteKnowledgeBase(knowledgeBase: KnowledgeBase) {
    modal.confirm({
      title: t("adminKnowledge.confirmDeleteTitle"),
      content: t("adminKnowledge.confirmDeleteKnowledgeMessage", { name: knowledgeBase.name }),
      okText: t("adminKnowledge.confirmDeleteConfirm"),
      okButtonProps: { danger: true },
      cancelText: t("adminKnowledge.confirmDeleteCancel"),
      onOk: () => handleDeleteKnowledgeBase(knowledgeBase),
    });
  }

  function confirmDeleteDocument(document: KnowledgeBaseDocument) {
    modal.confirm({
      title: t("adminKnowledge.confirmDeleteTitle"),
      content: t("adminKnowledge.confirmDeleteDocumentMessage", { name: document.fileName || document.id }),
      okText: t("adminKnowledge.confirmDeleteConfirm"),
      okButtonProps: { danger: true },
      cancelText: t("adminKnowledge.confirmDeleteCancel"),
      onOk: () => handleDeleteDocument(document),
    });
  }

  function confirmStatusChange(knowledgeBase: KnowledgeBase) {
    const isDisabling = knowledgeBase.status === "active";
    modal.confirm({
      title: isDisabling ? t("adminKnowledge.confirmDisableTitle") : t("adminKnowledge.confirmEnableTitle"),
      content: isDisabling
        ? t("adminKnowledge.confirmDisableMessage", { name: knowledgeBase.name })
        : t("adminKnowledge.confirmEnableMessage", { name: knowledgeBase.name }),
      okText: isDisabling ? t("adminKnowledge.confirmDisableConfirm") : t("adminKnowledge.confirmEnableConfirm"),
      okButtonProps: isDisabling ? { danger: true } : undefined,
      cancelText: t("adminKnowledge.confirmDeleteCancel"),
      onOk: () => handleSwitchKnowledgeStatus(knowledgeBase),
    });
  }

  const filteredKnowledgeBases = useMemo(() => {
    const normalizedKeyword = knowledgeKeyword.trim().toLowerCase();
    if (!normalizedKeyword) return knowledgeBases;

    return knowledgeBases.filter((row) => {
      const searchable = [row.name, row.description, row.status, row.ownerUserId]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      return searchable.includes(normalizedKeyword);
    });
  }, [knowledgeKeyword, knowledgeBases]);

  const selectedKnowledgeBase = useMemo(
    () => knowledgeBases.find((item) => item.id === selectedKnowledgeBaseId) ?? null,
    [knowledgeBases, selectedKnowledgeBaseId]
  );

  const filteredDocuments = useMemo(() => {
    const normalizedKeyword = documentKeyword.trim().toLowerCase();
    if (!normalizedKeyword) return documents;

    return documents.filter((document) => {
      const searchable = [
        document.fileName,
        document.fileType,
        document.mimeType,
        document.parseStatus,
        document.indexStatus,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      return searchable.includes(normalizedKeyword);
    });
  }, [documents, documentKeyword]);

  const documentStats = useMemo(() => {
    const total = documents.length;
    const completed = documents.filter((item) => {
      const parseOk = item.parseStatus === "ready";
      const indexOk = item.indexStatus === "ready";
      return parseOk && indexOk;
    }).length;
    const failed = documents.filter((item) => item.parseStatus === "failed" || item.indexStatus === "failed").length;
    const processing = documents.filter(
      (item) =>
        item.parseStatus === "pending" ||
        item.parseStatus === "processing" ||
        item.indexStatus === "pending" ||
        item.indexStatus === "processing"
    ).length;

    return { total, completed, failed, processing };
  }, [documents]);

  const parseStatusLabel = (status?: string) => {
    if (status === "pending") return t("adminKnowledge.statusPending");
    if (status === "processing") return t("adminKnowledge.statusProcessing");
    if (status === "ready") return t("adminKnowledge.statusReady");
    if (status === "failed") return t("adminKnowledge.statusFailed");
    return status || "-";
  };

  const indexStatusLabel = (status?: string) => {
    if (status === "pending") return t("adminKnowledge.statusPending");
    if (status === "stale") return t("adminKnowledge.statusStale");
    if (status === "processing") return t("adminKnowledge.statusProcessing");
    if (status === "ready") return t("adminKnowledge.statusReady");
    if (status === "failed") return t("adminKnowledge.statusFailed");
    return status || "-";
  };

  const documentStatusTag = (status: string | undefined, label: string) => {
    const color =
      status === "ready"
        ? "success"
        : status === "failed"
          ? "error"
          : status === "processing"
            ? "processing"
            : "default";
    return <Tag color={color}>{label}</Tag>;
  };

  const knowledgeIndexStatusTag = (status?: string) => {
    const label =
      status === "ready"
        ? t("adminKnowledge.kbIndexReady")
        : status === "failed"
          ? t("adminKnowledge.kbIndexFailed")
          : status === "deleting"
            ? t("adminKnowledge.kbIndexDeleting")
            : t("adminKnowledge.kbIndexProvisioning");
    const color = status === "ready" ? "success" : status === "failed" ? "error" : "processing";
    return <Tag color={color}>{t("adminKnowledge.kbIndexStatusLabel", { status: label })}</Tag>;
  };

  const formatUploadFailure = (failure: KnowledgeBaseUploadFailure) => {
    if (failure.code === "KB_DOCUMENT_DUPLICATE_CONTENT") {
      const duplicateFileName = String(failure.details?.duplicateFileName || "-");
      return t("adminKnowledge.uploadDuplicateContent", {
        fileName: failure.fileName,
        duplicateFileName,
      });
    }
    return t("adminKnowledge.uploadItemFailed", {
      fileName: failure.fileName,
      reason: failure.message,
    });
  };

  const documentColumns: TableColumnsType<KnowledgeBaseDocument> = [
    {
      title: t("adminKnowledge.colDocumentName"),
      key: "name",
      render: (_, document) => (
        <div>
          <div className="font-medium text-[#111827]">{document.fileName || document.id}</div>
          <div className="mt-1 text-xs text-[#8a8f98]">
            {[document.fileType?.toUpperCase(), formatFileSize(document.fileSizeBytes)].filter(Boolean).join(" · ") || "-"}
          </div>
        </div>
      ),
    },
    {
      title: t("adminKnowledge.colStatus"),
      key: "status",
      width: 320,
      render: (_, document) => {
        if (selectedKnowledgeBase?.status === "archived") {
          return <Tag>{t("adminKnowledge.syncPausedArchived")}</Tag>;
        }
        const parseTag = documentStatusTag(
          document.parseStatus,
          parseStatusLabel(document.parseStatus)
        );
        const indexTag = documentStatusTag(
          document.indexStatus,
          indexStatusLabel(document.indexStatus)
        );
        const syncError = document.lastError || document.parseError;
        return (
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-[#8a8f98]">{t("adminKnowledge.parseStatusLabel")}</span>
              {document.parseError ? <Tooltip title={document.parseError}>{parseTag}</Tooltip> : parseTag}
              <span className="text-xs text-[#8a8f98]">{t("adminKnowledge.indexStatusLabel")}</span>
              {indexTag}
            </div>
            {syncError ? (
              <Tooltip title={syncError}>
                <p className="mt-1 max-w-[300px] truncate text-xs text-[#b42318]">
                  {document.indexStatus === "pending"
                    ? t("adminKnowledge.retryPending", { error: syncError })
                    : syncError}
                </p>
              </Tooltip>
            ) : null}
          </div>
        );
      },
    },
    {
      title: t("adminKnowledge.colIndexVersion"),
      key: "indexVersion",
      width: 240,
      render: (_, document) =>
        document.indexPipelineVersion ? (
          <Text code>{document.indexPipelineVersion}</Text>
        ) : (
          <Text type="secondary">{t("adminKnowledge.indexVersionPending")}</Text>
        ),
    },
    { title: t("adminKnowledge.colUpdatedAt"), key: "updatedAt", render: (_, document) => formatDate(document.updatedAt) },
    {
      title: t("adminKnowledge.colActions"),
      key: "actions",
      width: 220,
      render: (_, document) => (
        <Space wrap>
          <Button size="small" onClick={() => void handleDownloadDocument(document)}>{t("adminKnowledge.view")}</Button>
          <Button size="small" onClick={() => void handleDownloadDocument(document)}>{t("adminKnowledge.download")}</Button>
          <Button size="small" danger loading={deletingDocumentId === document.id} onClick={() => confirmDeleteDocument(document)}>
            {t("adminKnowledge.delete")}
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div className="grid gap-[18px]">
      <div>
        <p className="text-xs uppercase tracking-[0.16em] text-[#6b7280]">{t("adminKnowledge.eyebrow")}</p>
        <Title level={3} className="!mt-1 !mb-0">{t("adminKnowledge.pageTitle")}</Title>
      </div>

      <Card styles={{ body: { padding: 18 } }}>
        <div className="grid min-h-[640px] grid-cols-1 gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
          <aside className="flex min-h-0 flex-col rounded-[8px] border border-[#e6e6e3] bg-[#f8fafc] p-3">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="text-base font-medium text-[#1f2933]">{t("adminKnowledge.knowledgeBaseHeading")}</h2>
              <Button
                size="small"
                type="text"
                icon={<PlusOutlined />}
                aria-label={t("adminKnowledge.addKnowledgeBaseAria")}
                onClick={openCreateModal}
              />
            </div>

            <Input
              allowClear
              value={knowledgeKeyword}
              onChange={(event) => setKnowledgeKeyword(event.target.value)}
              placeholder={t("adminKnowledge.searchKnowledgePlaceholder")}
              className="mb-3"
            />

            <div className="min-h-0 flex-1 space-y-1 overflow-y-auto overflow-x-hidden pr-1">
              {isKnowledgeLoading ? (
                <p className="rounded-[8px] border border-[#e2e8f0] bg-white px-3 py-6 text-center text-sm text-[#6b7280]">
                  {t("adminKnowledge.loadingKnowledgeBases")}
                </p>
              ) : filteredKnowledgeBases.length ? (
                filteredKnowledgeBases.map((knowledgeBase) => {
                  const isSelected = knowledgeBase.id === selectedKnowledgeBaseId;
                  return (
                    <button
                      key={knowledgeBase.id}
                      type="button"
                      className={`w-full rounded-[8px] border px-3 py-2 text-left ${
                        isSelected
                          ? "border-[#c9d5f2] bg-[#eef4ff]"
                          : "border-transparent bg-white hover:border-[#dbe3f3] hover:bg-[#f9fbff]"
                      }`}
                      onClick={() => setSelectedKnowledgeBaseId(knowledgeBase.id)}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <p className="truncate text-sm font-medium text-[#111827]">{knowledgeBase.name}</p>
                        {knowledgeStatusTag(t, knowledgeBase.status)}
                      </div>
                      <p className="mt-1 truncate text-xs text-[#6b7280]">{knowledgeBase.description || t("adminKnowledge.noDescription")}</p>
                    </button>
                  );
                })
              ) : (
                <p className="rounded-[8px] border border-[#e2e8f0] bg-white px-3 py-6 text-center text-sm text-[#6b7280]">
                  {knowledgeKeyword ? t("adminKnowledge.noMatchingKnowledgeBases") : t("adminKnowledge.noKnowledgeBases")}
                </p>
              )}
            </div>
          </aside>

          <div className="flex min-h-0 flex-col rounded-[8px] border border-[#e6e6e3] bg-[#fcfcfd] p-[18px]">
            {!selectedKnowledgeBase ? (
              <p className="rounded-[8px] border border-[#d6dbe6] bg-[#f8fafc] px-3 py-12 text-center text-sm text-[#6b7280]">
                {t("adminKnowledge.selectKnowledgeBasePrompt")}
              </p>
            ) : (
              <>
                <div className="mb-4 flex flex-wrap items-start justify-between gap-3 border-b border-[#edf1f5] pb-4">
                  <div className="min-w-0">
                    <div className="mb-1 flex items-center gap-2">
                      <span className="inline-block h-3 w-3 rounded-full bg-[#7c6cf4]" />
                      <h2 className="truncate text-[30px] font-medium leading-[1.1] text-[#1f2933]">{selectedKnowledgeBase.name}</h2>
                      {knowledgeStatusTag(t, selectedKnowledgeBase.status)}
                      {knowledgeIndexStatusTag(selectedKnowledgeBase.indexStatus)}
                    </div>
                    <p className="text-sm text-[#8a8f98]">{selectedKnowledgeBase.description || t("adminKnowledge.noKnowledgeBaseDescription")}</p>
                    <div className="mt-3 flex flex-wrap gap-5 text-sm text-[#4b5563]">
                      <span>{t("adminKnowledge.statTotal")} <strong className="ml-1 font-semibold text-[#111827]">{documentStats.total}</strong></span>
                      <span>{t("adminKnowledge.statCompleted")} <strong className="ml-1 font-semibold text-[#111827]">{documentStats.completed}</strong></span>
                      <span>{t("adminKnowledge.statFailed")} <strong className="ml-1 font-semibold text-[#111827]">{documentStats.failed}</strong></span>
                      <span>{t("adminKnowledge.statProcessing")} <strong className="ml-1 font-semibold text-[#111827]">{documentStats.processing}</strong></span>
                    </div>
                  </div>

                  <Space wrap>
                    {indexReview?.status === "review_required" ? (
                      <Button
                        type="primary"
                        ghost
                        icon={<ReloadOutlined />}
                        loading={isRebuildingIndex}
                        disabled={selectedKnowledgeBase.status !== "active"}
                        title={selectedKnowledgeBase.status !== "active" ? t("adminKnowledge.statusArchived") : undefined}
                        onClick={confirmRebuildIndex}
                      >
                        {isRebuildingIndex
                          ? t("adminKnowledge.rebuildingIndex")
                          : t("adminKnowledge.rebuildIndex")}
                      </Button>
                    ) : null}
                    <Button onClick={() => openEditModal(selectedKnowledgeBase)}>{t("adminKnowledge.edit")}</Button>
                    <Button
                      loading={isUploading}
                      disabled={!selectedKnowledgeBaseId}
                      onClick={() => uploadInputRef.current?.click()}
                    >
                      {t("adminKnowledge.uploadDocuments")}
                    </Button>
                    <Button
                      danger
                      loading={switchingStatusId === selectedKnowledgeBase.id}
                      onClick={() => confirmStatusChange(selectedKnowledgeBase)}
                    >
                      {selectedKnowledgeBase.status === "active" ? t("adminKnowledge.disable") : t("adminKnowledge.enable")}
                    </Button>
                    <Button
                      danger
                      loading={deletingKnowledgeBaseId === selectedKnowledgeBase.id}
                      disabled={selectedKnowledgeBase.status === "active"}
                      title={selectedKnowledgeBase.status === "active" ? t("adminKnowledge.deleteDisabledActiveHint") : undefined}
                      onClick={() => {
                        if (selectedKnowledgeBase.status === "active") return;
                        confirmDeleteKnowledgeBase(selectedKnowledgeBase);
                      }}
                    >
                      {t("adminKnowledge.delete")}
                    </Button>
                    <input
                      ref={uploadInputRef}
                      type="file"
                      multiple
                      className="hidden"
                      accept=".pdf,.docx,.pptx,.xlsx,.md,.txt,.html,.csv,.json"
                      onChange={(event) => {
                        const files = Array.from(event.target.files ?? []);
                        setSelectedFiles(files);
                        if (!files.length) return;
                        void handleUploadDocument(files);
                      }}
                    />
                  </Space>
                </div>

                <Space className="mb-3 w-full" wrap>
                  <Input
                    allowClear
                    value={documentKeyword}
                    onChange={(event) => setDocumentKeyword(event.target.value)}
                    placeholder={t("adminKnowledge.searchDocumentPlaceholder")}
                    style={{ width: 260 }}
                  />
                  <Button
                    icon={<ReloadOutlined spin={isDocumentLoading} />}
                    disabled={!selectedKnowledgeBaseId || isDocumentLoading}
                    aria-label={t("adminKnowledge.refreshDocumentsAria")}
                    onClick={() => {
                      if (!selectedKnowledgeBaseId) return;
                      void Promise.all([
                        loadKnowledgeBases({ showLoading: false }),
                        loadIndexReview(selectedKnowledgeBaseId),
                        loadDocuments(selectedKnowledgeBaseId),
                      ]);
                    }}
                  />
                </Space>

                {selectedFiles.length ? (
                  <p className="mb-3 rounded-[8px] border border-[#d6dbe6] bg-[#f8fafc] px-3 py-2 text-sm text-[#4b5563]">
                    {t("adminKnowledge.selectedLabel", {
                      value:
                        selectedFiles.length === 1
                          ? selectedFiles[0].name
                          : t("adminKnowledge.filesCount", { count: selectedFiles.length }),
                    })}
                  </p>
                ) : null}

                <div className="min-h-0 flex-1 overflow-auto">
                  <Table<KnowledgeBaseDocument>
                    rowKey="id"
                    columns={documentColumns}
                    dataSource={filteredDocuments}
                    loading={isDocumentLoading}
                    scroll={{ x: 960 }}
                    locale={{ emptyText: documentKeyword ? t("adminKnowledge.noMatchingDocuments") : t("adminKnowledge.noDocuments") }}
                    pagination={{ defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100] }}
                  />
                </div>
              </>
            )}
          </div>
        </div>
      </Card>

      <Modal
        open={isCreateModalOpen}
        title={t("adminKnowledge.addKnowledgeBaseTitle")}
        width={560}
        onCancel={() => setIsCreateModalOpen(false)}
        okText={isCreating ? t("adminKnowledge.creating") : t("adminKnowledge.createKnowledgeBase")}
        okButtonProps={{ loading: isCreating }}
        cancelText={t("adminKnowledge.confirmDeleteCancel")}
        onOk={() => createForm.submit()}
      >
        <Text type="secondary" className="mb-3 block text-sm">{t("adminKnowledge.createModalSubtitle")}</Text>
        <Form<CreateFormValues> form={createForm} layout="vertical" onFinish={handleCreateKnowledgeBase}>
          <Form.Item name="name" label={t("adminKnowledge.knowledgeBaseNameLabel")} rules={[{ required: true, whitespace: true }]}>
            <Input placeholder={t("adminKnowledge.knowledgeBaseNamePlaceholder")} />
          </Form.Item>
          <Form.Item name="description" label={t("adminKnowledge.descriptionLabel")}>
            <Input placeholder={t("adminKnowledge.descriptionPlaceholder")} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={Boolean(editingKnowledgeBase)}
        title={t("adminKnowledge.editModalTitle")}
        width={560}
        onCancel={() => setEditingKnowledgeBase(null)}
        okText={isUpdating ? t("adminKnowledge.saving") : t("adminKnowledge.saveProfile")}
        okButtonProps={{ loading: isUpdating }}
        cancelText={t("adminKnowledge.confirmDeleteCancel")}
        onOk={() => editForm.submit()}
      >
        <Text type="secondary" className="mb-3 block text-sm">{t("adminKnowledge.editModalSubtitle")}</Text>
        <Form<EditFormValues> form={editForm} layout="vertical" onFinish={handleUpdateKnowledgeBase}>
          <Form.Item name="name" label={t("adminKnowledge.knowledgeBaseNameLabel")} rules={[{ required: true, whitespace: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label={t("adminKnowledge.descriptionLabel")}>
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
