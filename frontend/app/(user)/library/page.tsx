"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { useDialog } from "@/lib/dialog";
import { useToast } from "@/lib/toast";
import { type ApiError } from "@/lib/request";
import {
  deleteLibraryFile,
  getLibraryFileDownload,
  getLibraryFilePreview,
  getLibraryFiles,
  promoteLibraryFile,
  uploadLibraryFile,
  type LibraryFileItem,
  type LibraryFileLifecycle,
  type LibraryFileType,
  type LibraryPreviewResponse,
} from "@/lib/api/library";
import { getCurrentSubscription } from "@/lib/api/plan-market";

type LibraryTab = "all" | LibraryFileType;
type LibraryScope = "personal" | "team";

const TEAM_STORAGE_LIMIT_BYTES = 20 * 1024 * 1024 * 1024;

const libraryTabs: { key: LibraryTab; labelKey: "userPages.library.all" | "userPages.library.image" | "userPages.library.file" }[] = [
  { key: "all", labelKey: "userPages.library.all" },
  { key: "image", labelKey: "userPages.library.image" },
  { key: "file", labelKey: "userPages.library.file" },
];

const lifecycleTabs: { key: LibraryFileLifecycle; labelKey: "userPages.library.lifecyclePermanent" | "userPages.library.lifecycleTemporary" }[] = [
  { key: "permanent", labelKey: "userPages.library.lifecyclePermanent" },
  { key: "temporary", labelKey: "userPages.library.lifecycleTemporary" },
];

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(2)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function SearchIcon({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="m21 21-4.3-4.3m2.3-5.2a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0Z" />
    </svg>
  );
}

function UploadIcon({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 16V4M7 9l5-5 5 5M5 20h14" />
    </svg>
  );
}

function getFileIcon(file: LibraryFileItem) {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (file.type === "image") return "image";
  if (extension === "csv") return "csv";
  if (["doc", "docx"].includes(extension)) return "doc";
  return "text";
}

function FileGlyph({ file }: { file: LibraryFileItem }) {
  const icon = getFileIcon(file);
  if (icon === "doc") return <span className="grid h-8 w-8 place-items-center rounded-[9px] bg-[#e8f3ff] text-[12px] font-bold text-[#25508b]">W</span>;
  if (icon === "csv") return <span className="grid h-8 w-8 place-items-center rounded-[9px] bg-[#edf7e5] text-[10px] font-bold text-[#4e7d24]">CSV</span>;
  if (icon === "image") {
    return (
      <span className="grid h-8 w-8 place-items-center rounded-[9px] bg-[#fff1d5] text-[#9a5f00]">
        <svg viewBox="0 0 24 24" className="h-[17px] w-[17px]" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M5 5h14v14H5zM8 15l2.5-3 2 2.4 1.5-1.8L18 17M9 9h.01" />
        </svg>
      </span>
    );
  }
  return (
    <span className="grid h-8 w-8 place-items-center rounded-[9px] bg-[#f0eee8] text-[#33302c]">
      <svg viewBox="0 0 24 24" className="h-[17px] w-[17px]" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h4" />
      </svg>
    </span>
  );
}

export default function LibraryPage() {
  const { t } = useI18n();
  const { confirm } = useDialog();
  const toast = useToast();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  // scope — persisted in localStorage; default "personal"
  const [scope, setScope] = useState<LibraryScope>("personal");
  const [isBusiness, setIsBusiness] = useState(false);
  const [subscriptionLoaded, setSubscriptionLoaded] = useState(false);

  // upload dialog (Business only)
  const [showUploadDialog, setShowUploadDialog] = useState(false);
  const [uploadTarget, setUploadTarget] = useState<LibraryScope>("personal");

  const [activeTab, setActiveTab] = useState<LibraryTab>("all");
  const [lifecycle, setLifecycle] = useState<LibraryFileLifecycle>("permanent");
  const [query, setQuery] = useState("");
  const [files, setFiles] = useState<LibraryFileItem[]>([]);
  const [openMenuId, setOpenMenuId] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [previewFile, setPreviewFile] = useState<LibraryFileItem | null>(null);
  const [preview, setPreview] = useState<LibraryPreviewResponse | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [previewLoadingId, setPreviewLoadingId] = useState("");
  const [operatingFileId, setOperatingFileId] = useState("");

  // Check Business plan once on mount
  useEffect(() => {
    const savedScope = (typeof window !== "undefined" ? localStorage.getItem("library-scope") : null) as LibraryScope | null;
    let ignore = false;
    if (savedScope === "personal" || savedScope === "team") {
      queueMicrotask(() => {
        if (!ignore) setScope(savedScope);
      });
    }

    getCurrentSubscription()
      .then((data) => {
        if (ignore) return;
        const business = (data.plan.entitlements?.seatLimit ?? 1) > 1;
        setIsBusiness(business);
        // If personal user but localStorage has "team", clean it up
        if (!business && savedScope === "team") {
          setScope("personal");
          if (typeof window !== "undefined") localStorage.setItem("library-scope", "personal");
        }
      })
      .catch(() => {})
      .finally(() => {
        if (!ignore) setSubscriptionLoaded(true);
      });
    return () => {
      ignore = true;
    };
  }, []);

  function handleScopeChange(newScope: LibraryScope) {
    setScope(newScope);
    setActiveTab("all");
    setQuery("");
    if (newScope === "personal") setLifecycle("permanent");
    if (typeof window !== "undefined") localStorage.setItem("library-scope", newScope);
  }

  function formatDate(value: string) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value || "-";
    const now = new Date();
    const isToday =
      date.getFullYear() === now.getFullYear() &&
      date.getMonth() === now.getMonth() &&
      date.getDate() === now.getDate();
    if (isToday) return t("userPages.common.today");
    return t("userPages.library.monthDay", { month: date.getMonth() + 1, day: date.getDate() });
  }

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setOpenMenuId("");
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpenMenuId("");
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  const debouncedKeyword = useDebouncedValue(query.trim(), 250);

  const effectiveScope: LibraryScope = isBusiness ? scope : "personal";
  // Team scope uses "permanent" lifecycle only; personal uses whichever toggle is set
  const effectiveLifecycle: LibraryFileLifecycle = effectiveScope === "team" ? "permanent" : lifecycle;

  // team storage — computed from team file list
  const teamUsedBytes = useMemo(() => {
    if (effectiveScope !== "team") return 0;
    return files.reduce((sum, f) => sum + f.sizeBytes, 0);
  }, [effectiveScope, files]);

  const requestParams = useMemo(
    () => ({
      keyword: debouncedKeyword || undefined,
      type: activeTab,
      lifecycle: effectiveLifecycle,
      spaceType: effectiveScope,
      page: 1,
      pageSize: 100,
      sort: "updatedAt_desc" as const,
    }),
    [activeTab, effectiveLifecycle, debouncedKeyword, effectiveScope],
  );

  useEffect(() => {
    if (!subscriptionLoaded) return;
    let ignore = false;
    queueMicrotask(() => { if (!ignore) setIsLoading(true); });

    const loadFiles = async () => {
      try {
        const response = await getLibraryFiles(requestParams);
        if (!ignore) setFiles(response.items ?? []);
      } catch (caughtError) {
        const apiError = caughtError as Partial<ApiError>;
        if (apiError.status === 401) return;
        if (!ignore) {
          setFiles([]);
          toast.error(apiError.message || t("userPages.library.loadFailed"));
        }
      } finally {
        if (!ignore) setIsLoading(false);
      }
    };

    void loadFiles();
    return () => { ignore = true; };
  }, [requestParams, subscriptionLoaded]);

  function handleUploadClick() {
    if (isBusiness) {
      setUploadTarget(effectiveScope);
      setShowUploadDialog(true);
    } else {
      fileInputRef.current?.click();
    }
  }

  function handleConfirmUpload() {
    setShowUploadDialog(false);
    fileInputRef.current?.click();
  }

  const handleUpload = async (selectedFiles: FileList | null) => {
    const file = selectedFiles?.[0];
    if (!file) return;
    setIsUploading(true);
    try {
      const uploadedFile = await uploadLibraryFile(file, uploadTarget);
      // Only add to current list if uploaded to same scope as displayed
      if (uploadTarget === effectiveScope) {
        setFiles((prev) => [uploadedFile, ...prev.filter((item) => item.id !== uploadedFile.id)]);
        setActiveTab("all");
        setLifecycle("permanent");
        setQuery("");
      }
    } catch (caughtError) {
      const apiError = caughtError as Partial<ApiError>;
      if (apiError.status === 401) return;
      toast.error(apiError.message || t("userPages.library.uploadFailed"));
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handlePreview = async (file: LibraryFileItem) => {
    setOpenMenuId("");
    setPreviewFile(file);
    setPreview(null);
    setPreviewError("");
    setPreviewLoadingId(file.id);
    try {
      setPreview(await getLibraryFilePreview(file.id));
    } catch (caughtError) {
      const apiError = caughtError as Partial<ApiError>;
      setPreviewError(apiError.message || t("userPages.library.previewFailed"));
    } finally {
      setPreviewLoadingId("");
    }
  };

  const handleDownload = async (file: LibraryFileItem) => {
    setOpenMenuId("");
    setOperatingFileId(file.id);
    try {
      const response = await getLibraryFileDownload(file.id);
      window.open(response.downloadUrl, "_blank", "noopener,noreferrer");
    } catch (caughtError) {
      const apiError = caughtError as Partial<ApiError>;
      toast.error(apiError.message || t("userPages.library.downloadFailed"));
    } finally {
      setOperatingFileId("");
    }
  };

  const handlePromote = async (file: LibraryFileItem) => {
    setOpenMenuId("");
    setOperatingFileId(file.id);
    try {
      await promoteLibraryFile(file.id);
      setFiles((prev) => prev.filter((item) => item.id !== file.id));
    } catch (caughtError) {
      const apiError = caughtError as Partial<ApiError>;
      if (apiError.status === 401) return;
      toast.error(
        apiError.status === 409
          ? t("userPages.library.promoteNotAllowed")
          : apiError.message || t("userPages.library.promoteFailed"),
      );
    } finally {
      setOperatingFileId("");
    }
  };

  const handleDelete = async (file: LibraryFileItem) => {
    setOpenMenuId("");
    if (!(await confirm({ message: t("userPages.library.deleteConfirm", { name: file.name }), tone: "danger" }))) return;
    setOperatingFileId(file.id);
    try {
      await deleteLibraryFile(file.id);
      setFiles((prev) => prev.filter((item) => item.id !== file.id));
    } catch (caughtError) {
      const apiError = caughtError as Partial<ApiError>;
      toast.error(apiError.message || t("userPages.library.deleteFailed"));
    } finally {
      setOperatingFileId("");
    }
  };

  const teamUsedPct = Math.min(100, Math.round((teamUsedBytes / TEAM_STORAGE_LIMIT_BYTES) * 100));
  const teamNearFull = teamUsedPct >= 90;

  return (
    <section className="mx-auto flex w-full max-w-[1040px] flex-col text-[#1f1b1d]" aria-label={t("userPages.library.title")}>
      {/* ── Header ── */}
      <header className="flex flex-col gap-5 pb-7 pt-2 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="mb-2 text-[13px] font-semibold uppercase tracking-[0.18em] text-[#f39c12]">{t("userPages.library.eyebrow")}</p>
          <h1 className="text-[30px] font-bold text-[#1d232c]">{t("userPages.library.title")}</h1>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row">
          <label className="flex h-[40px] w-full items-center gap-2 rounded-full border border-[#e3ded7] bg-white px-[14px] text-[#6f6860] sm:w-[260px]">
            <SearchIcon className="h-4 w-4 shrink-0 text-[#9b938b]" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("userPages.library.search")}
              className="min-w-0 flex-1 border-0 bg-transparent text-[14px] text-[#252b35] outline-none placeholder:text-[#9b938b]"
            />
          </label>
          <input ref={fileInputRef} type="file" className="hidden" onChange={(event) => void handleUpload(event.target.files)} />
          <button
            type="button"
            onClick={handleUploadClick}
            disabled={isUploading}
            className="inline-flex h-[40px] items-center justify-center gap-2 rounded-full bg-[#111] px-[18px] text-[14px] font-semibold text-white hover:bg-[#000] disabled:cursor-not-allowed disabled:bg-[#777]"
          >
            <UploadIcon />
            {isUploading ? t("userPages.library.uploading") : t("userPages.library.upload")}
          </button>
        </div>
      </header>

      {/* ── Personal / Team scope tabs (Business only) ── */}
      {isBusiness && (
        <div className="mb-4 flex gap-1 rounded-[12px] border border-[#e8e4de] bg-[#f7f5f2] p-1" aria-label="资料库类型" style={{ width: "fit-content" }}>
          <button
            type="button"
            onClick={() => handleScopeChange("personal")}
            className={`h-[34px] rounded-[9px] px-4 text-[14px] font-medium transition-all ${effectiveScope === "personal" ? "bg-white text-[#1f1b1d] shadow-[0_1px_3px_rgba(20,28,42,0.1)]" : "text-[#6f6860] hover:text-[#1f1b1d]"}`}
          >
            个人资料库
          </button>
          <button
            type="button"
            onClick={() => handleScopeChange("team")}
            className={`h-[34px] rounded-[9px] px-4 text-[14px] font-medium transition-all ${effectiveScope === "team" ? "bg-white text-[#1f1b1d] shadow-[0_1px_3px_rgba(20,28,42,0.1)]" : "text-[#6f6860] hover:text-[#1f1b1d]"}`}
          >
            团队资料库
          </button>
        </div>
      )}

      {/* ── Team storage meter ── */}
      {effectiveScope === "team" && (
        <div className="mb-4 rounded-[12px] border border-[#e8e4de] bg-white px-4 py-3">
          <div className="mb-1.5 flex items-center justify-between text-[13px]">
            <span className="text-[#5e5851]">团队资料库</span>
            <span className={`font-medium ${teamNearFull ? "text-[#9d3b31]" : "text-[#1f1b1d]"}`}>
              {formatBytes(teamUsedBytes)} / 20 GB
            </span>
          </div>
          <i className="block h-[5px] overflow-hidden rounded-full bg-[#ece9e4]">
            <b
              className="block h-full rounded-full transition-[width]"
              style={{ width: `${teamUsedPct}%`, backgroundColor: teamNearFull ? "#e8563a" : "#2f80ed" }}
            />
          </i>
          {teamNearFull && (
            <p className="mt-1.5 text-[12px] text-[#9d3b31]">存储空间即将用尽，请联系管理员清理文件</p>
          )}
        </div>
      )}

      {/* ── Type filter + lifecycle toggle ── */}
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-2 overflow-x-auto pb-1" aria-label={t("userPages.library.categoryLabel")}>
          {libraryTabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={`h-[38px] shrink-0 rounded-full px-[17px] text-[14px] transition ${activeTab === tab.key ? "bg-[#f0eeeb] text-[#1f1b1d] shadow-[inset_0_0_0_1px_#e0dbd4]" : "bg-transparent text-[#5e5851] hover:bg-[#f7f5f2]"}`}
            >
              {t(tab.labelKey)}
            </button>
          ))}
        </div>

        {/* Lifecycle toggle: personal only */}
        {effectiveScope === "personal" && (
          <div role="group" aria-label={t("userPages.library.lifecycleLabel")} className="inline-flex shrink-0 items-center gap-1 rounded-full bg-[#f0eeeb] p-1">
            {lifecycleTabs.map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => setLifecycle(tab.key)}
                aria-pressed={lifecycle === tab.key}
                className={`h-[32px] shrink-0 rounded-full px-[16px] text-[13px] font-medium transition ${lifecycle === tab.key ? "bg-white text-[#1f1b1d] shadow-[0_1px_3px_rgba(20,28,42,0.12)]" : "bg-transparent text-[#6f6860] hover:text-[#1f1b1d]"}`}
              >
                {t(tab.labelKey)}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ── File list ── */}
      <div className="rounded-[24px] border border-[#ece8e2] bg-white">
        {isLoading ? (
          <div className="grid min-h-[200px] place-items-center px-6 text-center text-[15px] text-[#6f6860]">{t("userPages.library.loadingFiles")}</div>
        ) : files.length ? (
          <div className={effectiveScope === "team" ? "min-w-[820px]" : "min-w-[720px]"}>
            {/* Table header */}
            {effectiveScope === "team" ? (
              <div className="grid grid-cols-[1fr_140px_150px_120px_56px] items-center border-b border-[#ece8e2] px-5 py-3 text-[13px] text-[#6f6860]">
                <span>{t("userPages.library.name")}</span>
                <span>上传者</span>
                <span>{t("userPages.library.modified")}</span>
                <span>{t("userPages.library.size")}</span>
                <span />
              </div>
            ) : (
              <div className="grid grid-cols-[1fr_150px_120px_56px] items-center border-b border-[#ece8e2] px-5 py-3 text-[13px] text-[#6f6860]">
                <span>{t("userPages.library.name")}</span>
                <span>{t("userPages.library.modified")}</span>
                <span>{t("userPages.library.size")}</span>
                <span />
              </div>
            )}

            {/* File rows */}
            {files.map((file) => (
              <article
                key={file.id}
                className={`relative border-b border-[#f0ede8] px-5 last:border-b-0 hover:bg-[#fbfaf8] ${openMenuId === file.id ? "bg-[#fbfaf8]" : ""} ${effectiveScope === "team" ? "grid min-h-[66px] grid-cols-[1fr_140px_150px_120px_56px] items-center" : "grid min-h-[66px] grid-cols-[1fr_150px_120px_56px] items-center"}`}
              >
                <div className="flex min-w-0 items-center gap-3">
                  <FileGlyph file={file} />
                  <span className="truncate text-[14px] font-medium text-[#252b35]">{file.name}</span>
                </div>
                {effectiveScope === "team" && (
                  <span className="text-[14px] text-[#5e5851]">—</span>
                )}
                <time className="text-[14px] text-[#5e5851]">{formatDate(file.updatedAt || file.createdAt)}</time>
                <em className="not-italic text-[14px] text-[#5e5851]">{file.sizeLabel}</em>
                <div className="relative flex justify-end">
                  <button
                    type="button"
                    onPointerDown={(event) => event.stopPropagation()}
                    onClick={(event) => {
                      event.stopPropagation();
                      setOpenMenuId((prev) => (prev === file.id ? "" : file.id));
                    }}
                    className="grid h-9 w-9 place-items-center rounded-[9px] text-[#8c8782] hover:bg-[#f0eeeb]"
                    aria-label={t("userPages.library.moreActions")}
                    disabled={operatingFileId === file.id}
                  >
                    ...
                  </button>
                  {openMenuId === file.id ? (
                    <div ref={menuRef} onPointerDown={(event) => event.stopPropagation()} className="absolute right-0 top-10 z-20 w-[148px] overflow-hidden rounded-[14px] border border-[#e0e4eb] bg-white shadow-[0_12px_34px_rgba(20,28,42,0.16)]">
                      {effectiveScope === "personal" && lifecycle === "temporary" ? (
                        <button type="button" onClick={() => void handlePromote(file)} className="flex h-11 w-full items-center border-b border-[#edf0f4] px-4 text-left text-[14px] font-medium text-[#1d6f42] hover:bg-[#f2faf5] disabled:text-[#a0a7b2]" disabled={operatingFileId === file.id}>
                          {operatingFileId === file.id ? t("userPages.library.promoting") : t("userPages.library.promote")}
                        </button>
                      ) : null}
                      <button type="button" onClick={() => void handlePreview(file)} className="flex h-11 w-full items-center px-4 text-left text-[14px] text-[#222832] hover:bg-[#f6f8fb] disabled:text-[#a0a7b2]" disabled={!file.previewSupported || previewLoadingId === file.id}>
                        {previewLoadingId === file.id ? t("userPages.library.previewLoading") : t("userPages.common.preview")}
                      </button>
                      <button type="button" onClick={() => void handleDownload(file)} className="flex h-11 w-full items-center border-t border-[#edf0f4] px-4 text-left text-[14px] text-[#222832] hover:bg-[#f6f8fb]">
                        {t("userPages.common.download")}
                      </button>
                      <button type="button" onClick={() => void handleDelete(file)} className="flex h-11 w-full items-center border-t border-[#edf0f4] px-4 text-left text-[14px] text-[#b42318] hover:bg-[#fff5f3]">
                        {t("userPages.common.delete")}
                      </button>
                    </div>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        ) : (
          /* Empty state */
          <div className="grid min-h-[200px] place-items-center px-6 text-center">
            {effectiveScope === "team" ? (
              <div>
                <span className="mx-auto grid h-[58px] w-[58px] place-items-center rounded-[18px] bg-[#f0eeeb] text-[#5f5a54]">
                  <svg viewBox="0 0 24 24" className="h-7 w-7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
                  </svg>
                </span>
                <p className="mt-4 text-[16px] font-semibold text-[#1f1b1d]">团队资料库还没有内容</p>
                <p className="mt-1.5 text-[13px] text-[#8a8580]">上传后，团队成员和 Agent 都能看到这份资料</p>
                <button
                  type="button"
                  onClick={handleUploadClick}
                  className="mt-4 inline-flex h-[38px] items-center gap-2 rounded-full bg-[#111] px-5 text-[14px] font-medium text-white hover:bg-[#000]"
                >
                  上传到团队
                </button>
              </div>
            ) : (
              <div>
                <span className="mx-auto grid h-[58px] w-[58px] place-items-center rounded-[18px] bg-[#f0eeeb] text-[#5f5a54]">
                  <SearchIcon className="h-7 w-7" />
                </span>
                <p className="mt-4 text-[15px] text-[#6f6860]">{t("userPages.library.empty")}</p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Upload dialog (Business only) ── */}
      {showUploadDialog && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/35 px-4" onPointerDown={() => setShowUploadDialog(false)}>
          <div className="w-full max-w-[420px] overflow-hidden rounded-[18px] bg-white shadow-[0_24px_60px_rgba(15,23,42,0.24)]" onPointerDown={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-[#ece8e2] px-5 py-4">
              <h2 className="text-[16px] font-semibold text-[#1f1b1d]">上传文件</h2>
              <button type="button" onClick={() => setShowUploadDialog(false)} className="grid h-8 w-8 place-items-center rounded-[8px] text-[#8c8782] hover:bg-[#f3f4f7]" aria-label="关闭">
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
              </button>
            </div>
            <div className="px-5 py-5">
              <fieldset className="mb-5">
                <legend className="mb-3 text-[13px] font-medium text-[#5e5851]">上传到</legend>
                <div className="flex flex-col gap-2.5">
                  <label className={`flex cursor-pointer items-center gap-3 rounded-[10px] border px-4 py-3 transition ${uploadTarget === "personal" ? "border-[#1f1b1d] bg-[#f7f5f2]" : "border-[#e3ded7] hover:bg-[#fbfaf8]"}`}>
                    <input type="radio" name="uploadTarget" value="personal" checked={uploadTarget === "personal"} onChange={() => setUploadTarget("personal")} className="accent-[#1f1b1d]" />
                    <div>
                      <p className="text-[14px] font-medium text-[#1f1b1d]">个人资料库</p>
                      <p className="text-[12px] text-[#8a8580]">仅自己可见</p>
                    </div>
                  </label>
                  <label className={`flex cursor-pointer items-center gap-3 rounded-[10px] border px-4 py-3 transition ${uploadTarget === "team" ? "border-[#1f1b1d] bg-[#f7f5f2]" : "border-[#e3ded7] hover:bg-[#fbfaf8]"}`}>
                    <input type="radio" name="uploadTarget" value="team" checked={uploadTarget === "team"} onChange={() => setUploadTarget("team")} className="accent-[#1f1b1d]" />
                    <div>
                      <p className="text-[14px] font-medium text-[#1f1b1d]">团队资料库</p>
                      <p className="text-[12px] text-[#8a8580]">团队成员和 Agent 都能看到</p>
                    </div>
                  </label>
                </div>
              </fieldset>
              <button
                type="button"
                onClick={handleConfirmUpload}
                className="h-[42px] w-full rounded-[10px] bg-[#111] text-[14px] font-semibold text-white hover:bg-[#000]"
              >
                选择文件
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Preview dialog ── */}
      {previewFile ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/35 px-4">
          <div className="flex max-h-[82vh] w-full max-w-[760px] flex-col overflow-hidden rounded-[18px] bg-white shadow-[0_24px_60px_rgba(15,23,42,0.24)]">
            <div className="flex items-center justify-between border-b border-[#ece8e2] px-5 py-4">
              <div className="min-w-0">
                <h2 className="truncate text-[16px] font-semibold text-[#1f1b1d]">{previewFile.name}</h2>
                <p className="mt-1 text-[12px] text-[#8b929e]">{t("userPages.library.previewTitle")}</p>
              </div>
              <button
                type="button"
                className="grid h-9 w-9 place-items-center rounded-[9px] text-[22px] hover:bg-[#f3f4f7]"
                onClick={() => { setPreviewFile(null); setPreview(null); setPreviewError(""); }}
                aria-label={t("userPages.library.closePreview")}
              >
                x
              </button>
            </div>
            <div className="min-h-[280px] overflow-auto p-5">
              {previewLoadingId ? <div className="grid min-h-[240px] place-items-center text-[14px] text-[#6f6860]">{t("userPages.library.loadingPreview")}</div> : null}
              {!previewLoadingId && previewError ? <p className="rounded-[10px] bg-[#fff4f2] px-4 py-3 text-[13px] text-[#b42318]">{previewError}</p> : null}
              {!previewLoadingId && !previewError && preview?.previewType === "text" ? <pre className="whitespace-pre-wrap rounded-[12px] bg-[#f6f7f9] p-4 text-[13px] leading-6 text-[#252b35]">{preview.content}</pre> : null}
              {!previewLoadingId && !previewError && preview?.previewType === "url" && preview.url ? (
                previewFile.type === "image" ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={preview.url} alt={previewFile.name} className="mx-auto max-h-[62vh] max-w-full rounded-[12px] object-contain" />
                ) : (
                  <iframe title={previewFile.name} src={preview.url} className="h-[62vh] w-full rounded-[12px] border border-[#ece8e2]" />
                )
              ) : null}
              {!previewLoadingId && !previewError && preview?.previewType === "unsupported" ? (
                <div className="grid min-h-[240px] place-items-center rounded-[12px] bg-[#f6f7f9] text-[14px] text-[#6f6860]">{t("userPages.library.unsupportedPreview")}</div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
