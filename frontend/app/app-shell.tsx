"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { AUTH_EXPIRED_EVENT, clearAuthState, type ApiError } from "@/lib/request";
import { removeSessionExpert } from "@/lib/session-expert";
import { LanguageSwitcher, translate, useI18n } from "@/lib/i18n";
import { useDialog } from "@/lib/dialog";
import {
  CHAT_SESSION_TITLE_HINT_EVENT,
  CHAT_SESSIONS_CHANGED_EVENT,
  deleteChatSession,
  getChatSessions,
  renameChatSession,
  searchChatSessions,
  setChatSessionArchived,
  setChatSessionPinned,
  type ChatSearchResultItem,
  type ChatSession,
  type ChatSessionTitleHint,
} from "@/lib/api/chat";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import {
  ArchiveIcon,
  ChevronIcon,
  ExpertsIcon,
  GearIcon,
  LibraryIcon,
  LightningIcon,
  LogoutIcon,
  MoreIcon,
  PlusIcon,
  SearchIcon,
  SidebarToggleIcon,
} from "./app-shell-icons";
import {
  buildHistoryGroups,
  getSessionId,
  getSessionList,
  readCookie,
  type HistoryItem,
} from "./app-shell-helpers";
import { getCurrentSubscription } from "@/lib/api/plan-market";

type AppShellProps = {
  children: React.ReactNode;
  userEmail?: string;
};

export default function AppShell({ children, userEmail = "" }: AppShellProps) {
  const { locale, t } = useI18n();
  const { confirm, prompt } = useDialog();
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const accountMenuRef = useRef<HTMLDivElement | null>(null);
  const sessionMenuRef = useRef<HTMLDivElement | null>(null);
  // Holds the latest openSearch so the (mount-only) keydown listener never calls a stale closure.
  const openSearchRef = useRef<() => void>(() => {});
  const showSidebar = pathname !== "/login" && pathname !== "/admin/login";
  const isSubscribePage = pathname === "/subscribe";
  const isAccountPage = pathname === "/account";
  const activeChat = pathname === "/dialogue" ? searchParams.get("chat") ?? "ads" : "";
  const isNewChatActive = pathname === "/";
  const isExpertsPage = pathname === "/experts";
  const isLibraryPage = pathname === "/library";
  const isArchivesPage = pathname === "/archives";
  const [displayEmail, setDisplayEmail] = useState(userEmail);
  const isLoggedIn = Boolean(displayEmail);
  const [isAccountMenuOpen, setIsAccountMenuOpen] = useState(false);
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([]);
  // Client-side title placeholders, kept only until the server returns a real (non-empty) title.
  const optimisticTitlesRef = useRef<Map<string, string>>(new Map());
  const [isCreatingSession] = useState(false);
  const [chatHistoryRefreshKey, setChatHistoryRefreshKey] = useState(0);
  const [createSessionError, setCreateSessionError] = useState("");
  const [sessionActionError, setSessionActionError] = useState("");
  const [openSessionMenuId, setOpenSessionMenuId] = useState("");
  const [operatingSessionId, setOperatingSessionId] = useState("");
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [backendSearchResults, setBackendSearchResults] = useState<ChatSearchResultItem[] | null>(null);
  const [isSearchLoading, setIsSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [currentPlanName, setCurrentPlanName] = useState<string | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const debouncedSearchQuery = useDebouncedValue(searchQuery, 300);

  const historyGroups = useMemo(() => buildHistoryGroups(chatSessions, locale), [chatSessions, locale]);

  // Shared nav-item layout: full-width row with label when expanded, centered icon square when collapsed.
  const navItemClass = `flex h-10 items-center rounded-[10px] text-[15px] ${
    isSidebarCollapsed ? "w-10 justify-center" : "w-full gap-3 px-3"
  }`;

  // Recent sessions shown in the search modal when no keyword has been typed yet.
  const recentSessions = useMemo(() => {
    return chatSessions
      .map((session) => {
        const id = getSessionId(session);
        if (!id) return null;
        const title = session.title || session.name || session.summary || translate(locale, "appShell.unnamedChat");
        return { id, title };
      })
      .filter((item): item is { id: string; title: string } => item !== null);
  }, [chatSessions, locale]);

  // Kick off a backend keyword search whenever the debounced query changes.
  useEffect(() => {
    const keyword = debouncedSearchQuery.trim();
    let cancelled = false;

    if (!keyword) {
      queueMicrotask(() => {
        if (cancelled) return;
        setBackendSearchResults(null);
        setSearchError("");
        setIsSearchLoading(false);
      });
      return () => {
        cancelled = true;
      };
    }

    queueMicrotask(() => {
      if (cancelled) return;
      setIsSearchLoading(true);
      setSearchError("");
    });

    searchChatSessions({ keyword, scope: "all", limit: 20, offset: 0 })
      .then((response) => {
        if (cancelled) return;
        setBackendSearchResults(response.items);
      })
      .catch((error) => {
        if (cancelled) return;
        const apiError = error as Partial<ApiError>;
        if (apiError.status === 401) return;
        setSearchError(apiError.message || t("appShell.searchLoadFailed"));
        setBackendSearchResults(null);
      })
      .finally(() => {
        if (cancelled) return;
        setIsSearchLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [debouncedSearchQuery, t]);

  useEffect(() => {
    let ignore = false;

    queueMicrotask(() => {
      if (!ignore) {
        setDisplayEmail(window.localStorage.getItem("user_email") || readCookie("user_email") || "");
      }
    });

    return () => {
      ignore = true;
    };
  }, [pathname]);

  useEffect(() => {
    if (!isLoggedIn) return;
    let ignore = false;

    getCurrentSubscription()
      .then((res) => {
        if (!ignore && res?.plan?.name) setCurrentPlanName(res.plan.name);
      })
      .catch(() => {});

    return () => { ignore = true; };
  }, [isLoggedIn]);

  useEffect(() => {
    let ignore = false;

    if (!displayEmail) {
      queueMicrotask(() => {
        if (!ignore) setChatSessions([]);
      });

      return () => {
        ignore = true;
      };
    }

    getChatSessions()
      .then((response) => {
        if (ignore) return;
        const hints = optimisticTitlesRef.current;
        const list = getSessionList(response).map((session) => {
          const id = getSessionId(session);
          if (session.title) {
            hints.delete(id); // server owns a real title now; drop the placeholder
            return session;
          }
          const hint = hints.get(id);
          return hint ? { ...session, title: hint } : session;
        });
        setChatSessions(list);
      })
      .catch(() => {
        if (!ignore) setChatSessions([]);
      });

    return () => {
      ignore = true;
    };
  }, [chatHistoryRefreshKey, displayEmail]);

  useEffect(() => {
    const handleChatSessionsChanged = () => {
      setChatHistoryRefreshKey((key) => key + 1);
    };

    const handleTitleHint = (event: Event) => {
      const detail = (event as CustomEvent<ChatSessionTitleHint>).detail;
      if (!detail?.sessionId || !detail.title) return;
      optimisticTitlesRef.current.set(detail.sessionId, detail.title);
      // Patch any already-listed session immediately; if it is not listed yet (brand-new chat
      // mid-refetch), the merge in the refetch above applies the hint once it lands.
      setChatSessions((prev) =>
        prev.map((session) =>
          getSessionId(session) === detail.sessionId
            ? { ...session, title: detail.title }
            : session,
        ),
      );
    };

    window.addEventListener(CHAT_SESSIONS_CHANGED_EVENT, handleChatSessionsChanged);
    window.addEventListener(CHAT_SESSION_TITLE_HINT_EVENT, handleTitleHint);
    return () => {
      window.removeEventListener(CHAT_SESSIONS_CHANGED_EVENT, handleChatSessionsChanged);
      window.removeEventListener(CHAT_SESSION_TITLE_HINT_EVENT, handleTitleHint);
    };
  }, []);

  useEffect(() => {
    const handleAuthExpired = () => {
      setDisplayEmail("");
      setChatSessions([]);
      setIsAccountMenuOpen(false);
      setOpenSessionMenuId("");
      router.replace("/login");
    };

    const onPointerDown = (event: PointerEvent) => {
      if (!accountMenuRef.current?.contains(event.target as Node)) {
        setIsAccountMenuOpen(false);
      }
      if (!sessionMenuRef.current?.contains(event.target as Node)) {
        setOpenSessionMenuId("");
      }
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && (event.key === "k" || event.key === "K")) {
        event.preventDefault();
        openSearchRef.current();
        return;
      }
      if (event.key === "Escape") {
        setIsAccountMenuOpen(false);
        setOpenSessionMenuId("");
        setIsSearchOpen(false);
      }
    };

    window.addEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [router]);

  useEffect(() => {
    if (isSearchOpen) searchInputRef.current?.focus();
  }, [isSearchOpen]);

  useEffect(() => {
    queueMicrotask(() => {
      setIsSidebarCollapsed(window.localStorage.getItem("sidebar_collapsed") === "1");
    });
  }, []);

  const toggleSidebarCollapsed = () => {
    setIsSidebarCollapsed((prev) => {
      const next = !prev;
      window.localStorage.setItem("sidebar_collapsed", next ? "1" : "0");
      return next;
    });
  };

  const handleLogout = () => {
    clearAuthState();
    setDisplayEmail("");
    setChatSessions([]);
    router.push("/login");
  };

  const updateSessionInList = (sessionId: string, nextSession: ChatSession) => {
    setChatSessions((prev) =>
      prev.map((session) => (getSessionId(session) === sessionId ? { ...session, ...nextSession } : session))
    );
  };

  const handleCreateSession = () => {
    if (!isLoggedIn) {
      router.push("/login");
      return;
    }

    setCreateSessionError("");
    setSessionActionError("");
    router.push("/");
  };

  const openSearch = () => {
    if (!isLoggedIn) {
      router.push("/login");
      return;
    }

    setIsSearchOpen(true);
    setSearchQuery("");
    setSearchError("");
    setBackendSearchResults(null);
    setIsSearchLoading(false);
  };

  const handleSelectSearchResult = (id: string) => {
    setIsSearchOpen(false);
    router.push(`/dialogue?chat=${encodeURIComponent(id)}`);
  };

  useEffect(() => {
    openSearchRef.current = openSearch;
  });

  const handleToggleSessionPinned = async (item: HistoryItem) => {
    setOperatingSessionId(item.id);
    setOpenSessionMenuId("");
    setSessionActionError("");

    try {
      const updatedSession = await setChatSessionPinned(item.id, { isPinned: !item.isPinned });
      updateSessionInList(item.id, updatedSession);
      window.dispatchEvent(new Event(CHAT_SESSIONS_CHANGED_EVENT));
    } catch (error) {
      const apiError = error as Partial<ApiError>;
      if (apiError.status === 401) return;
      setSessionActionError(apiError.message || t("appShell.updatePinFailed"));
    } finally {
      setOperatingSessionId("");
    }
  };

  const handleRenameSession = async (item: HistoryItem) => {
    setOpenSessionMenuId("");

    const nextTitle = (
      await prompt({ title: t("appShell.renamePrompt"), defaultValue: item.title })
    )?.trim();
    if (!nextTitle || nextTitle === item.title) return;

    setOperatingSessionId(item.id);
    setSessionActionError("");

    try {
      const updatedSession = await renameChatSession(item.id, { title: nextTitle });
      updateSessionInList(item.id, updatedSession);
      window.dispatchEvent(new Event(CHAT_SESSIONS_CHANGED_EVENT));
    } catch (error) {
      const apiError = error as Partial<ApiError>;
      if (apiError.status === 401) return;
      setSessionActionError(apiError.message || t("appShell.renameFailed"));
    } finally {
      setOperatingSessionId("");
    }
  };

  const handleDeleteSession = async (item: HistoryItem) => {
    setOpenSessionMenuId("");

    if (!(await confirm({ message: t("appShell.deleteConfirm", { title: item.title }), tone: "danger" }))) return;

    const previousSessions = chatSessions;
    const deletedSession = previousSessions.find((session) => getSessionId(session) === item.id);
    const deletedSessionIndex = previousSessions.findIndex((session) => getSessionId(session) === item.id);
    const wasActiveChat = activeChat === item.id;

    setOperatingSessionId(item.id);
    setSessionActionError("");
    setChatSessions((prev) => prev.filter((session) => getSessionId(session) !== item.id));

    if (wasActiveChat) {
      router.push("/dialogue");
    }

    try {
      await deleteChatSession(item.id);
      removeSessionExpert(item.id);
      window.dispatchEvent(new Event(CHAT_SESSIONS_CHANGED_EVENT));
    } catch (error) {
      const apiError = error as Partial<ApiError>;
      if (apiError.status === 401) return;

      if (deletedSession) {
        setChatSessions((current) => {
          if (current.some((session) => getSessionId(session) === item.id)) return current;

          const restored = [...current];
          restored.splice(Math.max(deletedSessionIndex, 0), 0, deletedSession);
          return restored;
        });
      }

      if (wasActiveChat) {
        router.push(`/dialogue?chat=${encodeURIComponent(item.id)}`);
      }

      setSessionActionError(apiError.message || t("appShell.deleteFailedRestored"));
    } finally {
      setOperatingSessionId("");
    }
  };

  const handleArchiveSession = async (item: HistoryItem) => {
    setOpenSessionMenuId("");

    const previousSessions = chatSessions;
    const archivedSession = previousSessions.find((session) => getSessionId(session) === item.id);
    const archivedSessionIndex = previousSessions.findIndex((session) => getSessionId(session) === item.id);
    const wasActiveChat = activeChat === item.id;

    setOperatingSessionId(item.id);
    setSessionActionError("");
    setChatSessions((prev) => prev.filter((session) => getSessionId(session) !== item.id));

    if (wasActiveChat) {
      router.push("/dialogue");
    }

    try {
      await setChatSessionArchived(item.id, { archived: true });
      window.dispatchEvent(new Event(CHAT_SESSIONS_CHANGED_EVENT));
    } catch (error) {
      const apiError = error as Partial<ApiError>;
      if (apiError.status === 401) return;

      if (archivedSession) {
        setChatSessions((current) => {
          if (current.some((session) => getSessionId(session) === item.id)) return current;

          const restored = [...current];
          restored.splice(Math.max(archivedSessionIndex, 0), 0, archivedSession);
          return restored;
        });
      }

      if (wasActiveChat) {
        router.push(`/dialogue?chat=${encodeURIComponent(item.id)}`);
      }

      setSessionActionError(apiError.message || t("appShell.archiveFailedRestored"));
    } finally {
      setOperatingSessionId("");
    }
  };

  if (!showSidebar) {
    return <>{children}</>;
  }

  if (isSubscribePage || isAccountPage) {
    return <div className="min-h-screen bg-[#ffffff] text-[#2a2d33]">{children}</div>;
  }

  return (
    <div className="h-screen overflow-hidden bg-[#ffffff] text-[#1f1b1d]">
      <div className="flex h-screen w-full overflow-hidden rounded-xl border border-[#ddd] bg-[#fff]">
        <aside
          className={`hidden h-screen flex-col border-r border-[#e8e3dc] bg-[#f8f7f5] lg:sticky lg:top-0 lg:flex ${
            isSidebarCollapsed ? "w-[68px] min-w-[68px]" : "w-[262px] min-w-[262px]"
          }`}
        >
          <div
            className={`px-[14px] py-[18px] ${
              isSidebarCollapsed ? "flex flex-col items-center gap-3" : "flex items-center justify-between"
            }`}
          >
            <Link href="/" aria-label="WinWise" className="inline-flex">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-[#232f3e] text-[15px] font-extrabold text-white">W</span>
            </Link>
            <button
              type="button"
              onClick={toggleSidebarCollapsed}
              aria-label={isSidebarCollapsed ? t("appShell.expandSidebar") : t("appShell.collapseSidebar")}
              title={isSidebarCollapsed ? t("appShell.expandSidebar") : t("appShell.collapseSidebar")}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-[#6b7280] hover:bg-[#fff4e2] hover:text-[#232f3e]"
            >
              <SidebarToggleIcon className="h-[18px] w-[18px]" />
            </button>
          </div>

          <div className={`pb-4 ${isSidebarCollapsed ? "px-[10px]" : "px-[14px]"}`}>
            <div className={`space-y-1 ${isSidebarCollapsed ? "" : "px-1"}`}>
              <button
                className={`${navItemClass} disabled:opacity-70 ${
                  isNewChatActive ? "bg-[#fff4e2] text-[#232f3e]" : "text-[#252b35] hover:bg-[#fff4e2] hover:text-[#232f3e]"
                }`}
                type="button"
                disabled={isCreatingSession}
                onClick={handleCreateSession}
                title={isSidebarCollapsed ? t("appShell.newChat") : undefined}
              >
                <PlusIcon className="h-[18px] w-[18px] shrink-0" />
                {!isSidebarCollapsed ? <span>{isCreatingSession ? t("appShell.creating") : t("appShell.newChat")}</span> : null}
              </button>
              <button
                type="button"
                onClick={openSearch}
                className={`${navItemClass} text-[#252b35] hover:bg-[#fff4e2] hover:text-[#232f3e]`}
                title={isSidebarCollapsed ? t("appShell.search") : undefined}
              >
                <SearchIcon className="h-[18px] w-[18px] shrink-0" />
                {!isSidebarCollapsed ? <span>{t("appShell.search")}</span> : null}
              </button>
              <Link
                href="/experts"
                className={`${navItemClass} ${
                  isExpertsPage ? "bg-[#fff4e2] text-[#232f3e]" : "text-[#252b35] hover:bg-[#fff4e2] hover:text-[#232f3e]"
                }`}
                title={isSidebarCollapsed ? t("appShell.experts") : undefined}
              >
                <ExpertsIcon className="h-[18px] w-[18px] shrink-0" />
                {!isSidebarCollapsed ? <span>{t("appShell.experts")}</span> : null}
              </Link>
              <Link
                href="/library"
                className={`${navItemClass} ${
                  isLibraryPage ? "bg-[#fff4e2] text-[#232f3e]" : "text-[#252b35] hover:bg-[#fff4e2] hover:text-[#232f3e]"
                }`}
                title={isSidebarCollapsed ? t("appShell.library") : undefined}
              >
                <LibraryIcon className="h-[18px] w-[18px] shrink-0" />
                {!isSidebarCollapsed ? <span>{t("appShell.library")}</span> : null}
              </Link>
              <Link
                href="/archives"
                className={`${navItemClass} ${
                  isArchivesPage ? "bg-[#fff4e2] text-[#232f3e]" : "text-[#252b35] hover:bg-[#fff4e2] hover:text-[#232f3e]"
                }`}
                title={isSidebarCollapsed ? t("appShell.archives") : undefined}
              >
                <ArchiveIcon className="h-[18px] w-[18px] shrink-0" />
                {!isSidebarCollapsed ? <span>{t("appShell.archives")}</span> : null}
              </Link>
            </div>
            {createSessionError ? (
              <p className="mt-2 px-2 text-xs leading-5 text-[#b42318]">{createSessionError}</p>
            ) : null}
            {sessionActionError ? (
              <p className="mt-2 px-2 text-xs leading-5 text-[#b42318]">{sessionActionError}</p>
            ) : null}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-[10px] pb-2">
            {isSidebarCollapsed ? null : historyGroups.map((group) => (
              <section key={group.label} className="mb-[18px]">
                <h2 className="mb-2 px-3 text-[13px] font-medium text-[#9ba1ad]">{group.label}</h2>
                <div className="space-y-1">
                  {group.items.map((item) => (
                    <div key={item.id} className="group/session relative">
                      <Link
                        href={`/dialogue?chat=${item.id}`}
                        className={`grid h-[41px] w-full grid-cols-[minmax(0,1fr)_28px] items-center rounded-xl py-0 pl-3 pr-1 text-left text-[14px] ${
                          activeChat === item.id ? "bg-[#eef0f5] text-[#1f242d]" : "text-[#1f242d] hover:bg-[#eef0f5]"
                        }`}
                      >
                        <span className="truncate">{item.title}</span>
                        <span aria-hidden="true" />
                      </Link>
                      <button
                        type="button"
                        disabled={operatingSessionId === item.id}
                        aria-label={t("appShell.moreSessionActions")}
                        className={`absolute right-1 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-lg text-[#6b7280] hover:bg-white hover:text-[#111827] disabled:opacity-50 ${
                          openSessionMenuId === item.id ? "bg-white opacity-100" : "opacity-0 group-hover/session:opacity-100"
                        }`}
                        onClick={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          setOpenSessionMenuId((prev) => (prev === item.id ? "" : item.id));
                        }}
                      >
                        <MoreIcon className="h-4 w-4" />
                      </button>
                      {openSessionMenuId === item.id ? (
                        <div
                          ref={sessionMenuRef}
                          className="absolute right-1 top-9 z-30 w-[148px] overflow-hidden rounded-[12px] border border-[#e0e4eb] bg-white py-1 shadow-[0_12px_34px_rgba(20,28,42,0.16)]"
                        >
                          <button
                            type="button"
                            onClick={() => void handleToggleSessionPinned(item)}
                            className="flex h-9 w-full items-center px-3 text-left text-[13px] text-[#222832] hover:bg-[#f6f8fb]"
                          >
                            {item.isPinned ? t("appShell.unpin") : t("appShell.pinSession")}
                          </button>
                          <button
                            type="button"
                            onClick={() => void handleRenameSession(item)}
                            className="flex h-9 w-full items-center border-t border-[#edf0f4] px-3 text-left text-[13px] text-[#222832] hover:bg-[#f6f8fb]"
                          >{t("appShell.rename")}</button>
                          <button
                            type="button"
                            onClick={() => void handleArchiveSession(item)}
                            className="flex h-9 w-full items-center border-t border-[#edf0f4] px-3 text-left text-[13px] text-[#222832] hover:bg-[#f6f8fb]"
                          >{t("appShell.archiveSession")}</button>
                          <button
                            type="button"
                            onClick={() => void handleDeleteSession(item)}
                            className="flex h-9 w-full items-center border-t border-[#edf0f4] px-3 text-left text-[13px] text-[#b42318] hover:bg-[#fff5f3]"
                          >{t("appShell.delete")}</button>
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>

          <div
            ref={accountMenuRef}
            className={`profile-row flex items-center border-t border-transparent py-[18px] ${
              isSidebarCollapsed ? "justify-center px-[10px]" : "gap-2 px-[14px]"
            }`}
          >
            <button
              className={`avatar flex h-8 w-8 items-center justify-center rounded-full border-0 text-[12px] font-bold ${
                isLoggedIn ? "bg-[#e8f4ff] text-[#1f3f62]" : "logged-out bg-[#fff4e2] text-[#232f3e]"
              }`}
              type="button"
              id="profileLogin"
              title={isSidebarCollapsed ? (isLoggedIn ? displayEmail : t("appShell.loginWinWise")) : undefined}
              onClick={() => (isLoggedIn ? setIsAccountMenuOpen((prev) => !prev) : router.push("/login"))}
            >
              {isLoggedIn ? displayEmail.slice(0, 1).toUpperCase() : "ww"}
            </button>
            {!isSidebarCollapsed ? (
              <>
                <button
                  className="profile-name min-w-0 border-0 bg-transparent text-left"
                  type="button"
                  id="profileName"
                  onClick={() => (isLoggedIn ? setIsAccountMenuOpen((prev) => !prev) : router.push("/login"))}
                >
                  <strong className="block truncate text-[14px] font-semibold text-[#20242b]">{isLoggedIn ? displayEmail : t("appShell.loginWinWise")}</strong>
                  <span className="block text-[12px] text-[#8b929e]">{isLoggedIn ? t("appShell.loggedIn") : t("appShell.freePlanEn")}</span>
                </button>
                <button
                  className="icon-btn small ml-auto inline-flex h-8 w-8 items-center justify-center rounded-full border border-[#e8e3dc] bg-white text-[#404852]"
                  type="button"
                  aria-label={t("appShell.accountMenu")}
                  onClick={() => (isLoggedIn ? setIsAccountMenuOpen((prev) => !prev) : router.push("/login"))}
                >
                  <ChevronIcon className="h-4 w-4" />
                </button>
              </>
            ) : null}

            {isLoggedIn ? (
              <div className={`account-menu ${isAccountMenuOpen ? "" : "hidden"}`} aria-hidden={!isAccountMenuOpen}>
                <div className="account-head">
                  <strong>{displayEmail}</strong>
                  <span>{currentPlanName ?? t("appShell.freePlan")}</span>
                </div>
                <button type="button" onClick={() => router.push("/subscribe")}>
                  <LightningIcon />
                  {t("appShell.upgrade")}
                </button>
                <button type="button" onClick={() => router.push("/account")}>
                  <GearIcon />
                  {t("appShell.account")}
                </button>
                <button className="logout" type="button" onClick={handleLogout}>
                  <LogoutIcon />
                  {t("appShell.logout")}
                </button>
              </div>
            ) : null}
          </div>
        </aside>

        <main className="flex h-full min-w-0 flex-1 flex-col overflow-hidden">
          <header className="flex shrink-0 items-center justify-end px-4 pt-4 sm:px-6 lg:px-8">
            <LanguageSwitcher />
          </header>
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 pb-6 pt-4 sm:px-6 lg:px-8">{children}</div>
        </main>
      </div>

      {isSearchOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center bg-[rgba(20,28,42,0.32)] px-4 pt-[12vh]"
          onMouseDown={() => setIsSearchOpen(false)}
        >
          <div
            className="flex max-h-[70vh] w-full max-w-[560px] flex-col overflow-hidden rounded-[16px] border border-[#e3ded7] bg-white shadow-[0_24px_64px_rgba(20,28,42,0.24)]"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <label className="flex h-[52px] shrink-0 items-center gap-3 border-b border-[#eee9e2] px-4 text-[#6f6860]">
              <SearchIcon className="h-[18px] w-[18px] shrink-0 text-[#9b938b]" />
              <input
                ref={searchInputRef}
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder={t("appShell.searchPlaceholder")}
                className="min-w-0 flex-1 border-0 bg-transparent text-[15px] text-[#252b35] outline-none placeholder:text-[#9b938b]"
              />
            </label>

            <div className="min-h-0 flex-1 overflow-y-auto py-2">
              {searchError ? (
                <p className="px-4 py-3 text-[13px] text-[#b42318]">{searchError}</p>
              ) : isSearchLoading ? (
                <p className="px-4 py-6 text-center text-[13px] text-[#9ba1ad]">{t("appShell.searchLoading")}</p>
              ) : backendSearchResults !== null ? (
                backendSearchResults.length > 0 ? (
                  backendSearchResults.map((result) => (
                    <button
                      key={result.sessionId}
                      type="button"
                      onClick={() => handleSelectSearchResult(result.sessionId)}
                      className="flex w-full flex-col px-4 py-2.5 text-left hover:bg-[#f6f8fb]"
                    >
                      <span className="min-w-0 w-full truncate text-[14px] text-[#1f242d]">
                        {result.title || t("appShell.unnamedChat")}
                      </span>
                      {result.snippet ? (
                        <span className="mt-0.5 line-clamp-1 text-[12px] text-[#9ba1ad]">
                          {result.snippet}
                        </span>
                      ) : null}
                    </button>
                  ))
                ) : (
                  <p className="px-4 py-6 text-center text-[13px] text-[#9ba1ad]">{t("appShell.searchEmpty")}</p>
                )
              ) : recentSessions.length > 0 ? (
                recentSessions.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => handleSelectSearchResult(item.id)}
                    className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-[#f6f8fb]"
                  >
                    <span className="min-w-0 flex-1 truncate text-[14px] text-[#1f242d]">{item.title}</span>
                  </button>
                ))
              ) : (
                <p className="px-4 py-6 text-center text-[13px] text-[#9ba1ad]">
                  {t("appShell.searchHint")}
                </p>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}





