"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useI18n } from "@/lib/i18n";
import { useDialog } from "@/lib/dialog";
import { useToast } from "@/lib/toast";
import { type ApiError } from "@/lib/request";
import {
  CHAT_SESSIONS_CHANGED_EVENT,
  deleteChatSession,
  getChatSessions,
  setChatSessionArchived,
  type ChatSession,
} from "@/lib/api/chat";

function SearchIcon({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="m21 21-4.3-4.3m2.3-5.2a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0Z" />
    </svg>
  );
}

function BatchIcon({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01" />
    </svg>
  );
}

function getSessionId(session: ChatSession) {
  return String(session.id ?? session.sessionId ?? session.chatId ?? "");
}

function getSessionList(response: Awaited<ReturnType<typeof getChatSessions>> | undefined): ChatSession[] {
  if (!response) return [];
  if (Array.isArray(response)) return response;

  if ("sessions" in response && Array.isArray(response.sessions)) return response.sessions;
  if ("items" in response && Array.isArray(response.items)) return response.items;
  if ("records" in response && Array.isArray(response.records)) return response.records;
  if (!("data" in response)) return [];

  const data = response.data;
  if (Array.isArray(data)) return data;
  if (!data) return [];

  const nestedData = data as {
    sessions?: ChatSession[];
    items?: ChatSession[];
    records?: ChatSession[];
  };

  if (Array.isArray(nestedData.sessions)) return nestedData.sessions;
  if (Array.isArray(nestedData.items)) return nestedData.items;
  if (Array.isArray(nestedData.records)) return nestedData.records;

  return [];
}

export default function ArchivesPage() {
  const router = useRouter();
  const { t } = useI18n();
  const { confirm } = useDialog();
  const toast = useToast();
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [restoringId, setRestoringId] = useState("");
  const [deletingId, setDeletingId] = useState("");
  const [batchMode, setBatchMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [isBatchProcessing, setIsBatchProcessing] = useState(false);

  function formatDateTime(value?: string) {
    if (!value) return t("userPages.common.unknownTime");

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;

    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  }

  const filteredSessions = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return sessions;

    return sessions.filter((session) => {
      const text = [session.title, session.name, session.summary, session.status].filter(Boolean).join(" ").toLowerCase();
      return text.includes(keyword);
    });
  }, [query, sessions]);

  useEffect(() => {
    let ignore = false;

    queueMicrotask(() => {
      if (!ignore) {
        setIsLoading(true);
      }
    });

    const loadArchivedSessions = async () => {
      try {
        const response = await getChatSessions({ status: "archived" });
        if (!ignore) setSessions(getSessionList(response));
      } catch (caughtError) {
        const apiError = caughtError as Partial<ApiError>;
        // Session expiry is redirected globally by the request interceptor.
        if (apiError.status === 401) return;

        if (!ignore) {
          setSessions([]);
          toast.error(apiError.message || t("userPages.archives.loadFailed"));
        }
      } finally {
        if (!ignore) setIsLoading(false);
      }
    };

    void loadArchivedSessions();

    return () => {
      ignore = true;
    };
  }, [router, t]);

  const handleRestore = async (session: ChatSession) => {
    const sessionId = getSessionId(session);
    if (!sessionId) return;

    setRestoringId(sessionId);

    try {
      await setChatSessionArchived(sessionId, { archived: false });
      setSessions((prev) => prev.filter((item) => getSessionId(item) !== sessionId));
      window.dispatchEvent(new Event(CHAT_SESSIONS_CHANGED_EVENT));
    } catch (caughtError) {
      const apiError = caughtError as Partial<ApiError>;
      if (apiError.status === 401) return;

      toast.error(apiError.message || t("userPages.archives.restoreFailed"));
    } finally {
      setRestoringId("");
    }
  };

  const handleDelete = async (session: ChatSession) => {
    const sessionId = getSessionId(session);
    const title = session.title || session.name || session.summary || t("userPages.common.unnamedChat");
    if (!sessionId) return;
    if (!(await confirm({ message: t("userPages.archives.deleteConfirm", { title }), tone: "danger" }))) return;

    setDeletingId(sessionId);

    try {
      await deleteChatSession(sessionId);
      setSessions((prev) => prev.filter((item) => getSessionId(item) !== sessionId));
      window.dispatchEvent(new Event(CHAT_SESSIONS_CHANGED_EVENT));
    } catch (caughtError) {
      const apiError = caughtError as Partial<ApiError>;
      if (apiError.status === 401) return;

      toast.error(apiError.message || t("userPages.archives.deleteFailed"));
    } finally {
      setDeletingId("");
    }
  };

  const toggleBatchMode = () => {
    setBatchMode((prev) => !prev);
    setSelectedIds(new Set());
  };

  const toggleSelection = (sessionId: string) => {
    if (!sessionId) return;
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(sessionId)) next.delete(sessionId);
      else next.add(sessionId);
      return next;
    });
  };

  const filteredIds = useMemo(() => filteredSessions.map(getSessionId).filter(Boolean), [filteredSessions]);
  const allSelected = filteredIds.length > 0 && filteredIds.every((id) => selectedIds.has(id));

  const toggleSelectAll = () => {
    setSelectedIds(allSelected ? new Set() : new Set(filteredIds));
  };

  const removeSessions = (ids: Set<string>) => {
    setSessions((prev) => prev.filter((item) => !ids.has(getSessionId(item))));
    setSelectedIds(new Set());
  };

  // Session expiry is redirected globally by the request interceptor; batch
  // handlers only need to stop further processing once it is detected.
  const isAuthExpired = (caughtError: unknown) =>
    (caughtError as Partial<ApiError>).status === 401;

  const handleBatchRestore = async () => {
    const ids = Array.from(selectedIds);
    if (!ids.length || isBatchProcessing) return;

    setIsBatchProcessing(true);

    try {
      await Promise.all(ids.map((id) => setChatSessionArchived(id, { archived: false })));
      removeSessions(new Set(ids));
      window.dispatchEvent(new Event(CHAT_SESSIONS_CHANGED_EVENT));
    } catch (caughtError) {
      if (isAuthExpired(caughtError)) return;
      const apiError = caughtError as Partial<ApiError>;
      toast.error(apiError.message || t("userPages.archives.batchRestoreFailed"));
    } finally {
      setIsBatchProcessing(false);
    }
  };

  const handleBatchDelete = async () => {
    const ids = Array.from(selectedIds);
    if (!ids.length || isBatchProcessing) return;
    if (!(await confirm({ message: t("userPages.archives.batchDeleteConfirm", { count: ids.length }), tone: "danger" }))) return;

    setIsBatchProcessing(true);

    try {
      await Promise.all(ids.map((id) => deleteChatSession(id)));
      removeSessions(new Set(ids));
      window.dispatchEvent(new Event(CHAT_SESSIONS_CHANGED_EVENT));
    } catch (caughtError) {
      if (isAuthExpired(caughtError)) return;
      const apiError = caughtError as Partial<ApiError>;
      toast.error(apiError.message || t("userPages.archives.batchDeleteFailed"));
    } finally {
      setIsBatchProcessing(false);
    }
  };

  return (
    <section className="mx-auto flex w-full max-w-[1040px] flex-col text-[#1f1b1d]">
      <header className="flex flex-col gap-5 pb-7 pt-2 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-[30px] font-bold text-[#1d232c]">{t("userPages.archives.title")}</h1>
          <p className="mt-2 text-[14px] text-[#777d88]">{t("userPages.archives.description")}</p>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row">
          <label className="flex h-[40px] w-full items-center gap-2 rounded-full border border-[#e3ded7] bg-white px-[14px] text-[#6f6860] sm:w-[260px]">
            <SearchIcon className="h-4 w-4 shrink-0 text-[#9b938b]" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("userPages.archives.search")} className="min-w-0 flex-1 border-0 bg-transparent text-[14px] text-[#252b35] outline-none placeholder:text-[#9b938b]" />
          </label>
          <button type="button" onClick={toggleBatchMode} disabled={isBatchProcessing} className="inline-flex h-[40px] items-center justify-center gap-2 rounded-full bg-[#111] px-[18px] text-[14px] font-semibold text-white hover:bg-[#000] disabled:cursor-not-allowed disabled:bg-[#777]">
            <BatchIcon />
            {batchMode ? t("userPages.archives.exitBatch") : t("userPages.archives.batchManage")}
          </button>
        </div>
      </header>

      {batchMode ? (
        <div className="mb-5 flex flex-wrap items-center gap-3 rounded-[18px] border border-[#ece8e2] bg-white px-4 py-3">
          <button type="button" className="inline-flex h-[36px] items-center rounded-full border border-[#e3ded7] bg-white px-[15px] text-[13px] text-[#252930] hover:bg-[#f7f5f2] disabled:cursor-not-allowed disabled:opacity-60" onClick={toggleSelectAll} disabled={!filteredIds.length || isBatchProcessing}>
            {allSelected ? t("userPages.archives.clearSelection") : t("userPages.archives.selectAll")}
          </button>
          <span className="text-[13px] text-[#777d88]">{t("userPages.archives.selectedCount", { count: selectedIds.size })}</span>
          <div className="ml-auto flex items-center gap-2">
            <button type="button" className="inline-flex h-[36px] items-center rounded-full bg-[#111] px-[15px] text-[13px] font-semibold text-white hover:bg-[#000] disabled:cursor-not-allowed disabled:bg-[#777]" onClick={() => void handleBatchRestore()} disabled={!selectedIds.size || isBatchProcessing}>
              {t("userPages.archives.restoreSelected")}
            </button>
            <button type="button" className="inline-flex h-[36px] items-center rounded-full border border-[#f1c8c3] bg-white px-[15px] text-[13px] font-semibold text-[#b42318] hover:bg-[#fff5f3] disabled:cursor-not-allowed disabled:opacity-60" onClick={() => void handleBatchDelete()} disabled={!selectedIds.size || isBatchProcessing}>
              {t("userPages.archives.deleteSelected")}
            </button>
          </div>
        </div>
      ) : null}

      <div className="rounded-[24px] border border-[#ece8e2] bg-white">
        <div className="border-b border-[#ece8e2] px-5 py-4">
          <span className="text-[14px] font-semibold text-[#252930]">{t("userPages.archives.total", { count: filteredSessions.length })}</span>
        </div>

        {isLoading ? (
          <div className="grid min-h-[200px] place-items-center text-[14px] text-[#777d88]">{t("userPages.archives.loading")}</div>
        ) : filteredSessions.length ? (
          <div className="divide-y divide-[#edf0f4]">
            {filteredSessions.map((session) => {
              const sessionId = getSessionId(session);
              const title = session.title || session.name || session.summary || t("userPages.common.unnamedChat");

              const isSelected = selectedIds.has(sessionId);

              return (
                <article key={sessionId || title} className="grid gap-3 px-5 py-4 hover:bg-[#fbfaf8] md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
                  <div className="flex min-w-0 items-start gap-3">
                    {batchMode ? (
                      <input type="checkbox" className="mt-1 h-4 w-4 shrink-0 cursor-pointer accent-[#232f3e]" checked={isSelected} onChange={() => toggleSelection(sessionId)} disabled={!sessionId || isBatchProcessing} aria-label={title} />
                    ) : null}
                    <div className="min-w-0">
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <h2 className="truncate text-[15px] font-semibold text-[#1f1b1d]">{title}</h2>
                        <span className="rounded-full bg-[#eef0f5] px-2 py-0.5 text-[12px] text-[#5f6876]">{t("userPages.archives.archived")}</span>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-3 text-[12px] text-[#9ba1ad]">
                        <span>{t("userPages.archives.updatedAt", { time: formatDateTime(session.updatedAt || session.lastMessageAt || session.createdAt) })}</span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2" hidden={batchMode}>
                    <button type="button" className="inline-flex h-[36px] items-center rounded-full border border-[#e3ded7] bg-white px-[15px] text-[13px] text-[#252930] hover:bg-[#f7f5f2]" onClick={() => sessionId && router.push(`/dialogue?chat=${encodeURIComponent(sessionId)}`)} disabled={!sessionId}>
                      {t("userPages.archives.view")}
                    </button>
                    <button type="button" className="inline-flex h-[36px] items-center rounded-full bg-[#111] px-[15px] text-[13px] font-semibold text-white hover:bg-[#000] disabled:cursor-not-allowed disabled:bg-[#777]" onClick={() => void handleRestore(session)} disabled={!sessionId || restoringId === sessionId || deletingId === sessionId}>
                      {restoringId === sessionId ? t("userPages.archives.restoring") : t("userPages.archives.restore")}
                    </button>
                    <button type="button" className="inline-flex h-[36px] items-center rounded-full border border-[#f1c8c3] bg-white px-[15px] text-[13px] font-semibold text-[#b42318] hover:bg-[#fff5f3] disabled:cursor-not-allowed disabled:opacity-60" onClick={() => void handleDelete(session)} disabled={!sessionId || deletingId === sessionId || restoringId === sessionId}>
                      {deletingId === sessionId ? t("userPages.common.deleting") : t("userPages.common.delete")}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <div className="grid min-h-[200px] place-items-center px-6 text-center">
            <strong className="text-[15px] text-[#252930]">{t("userPages.archives.empty")}</strong>
            <span className="mt-2 text-[13px] text-[#8b929e]">{t("userPages.archives.emptyHint")}</span>
          </div>
        )}
      </div>
    </section>
  );
}
