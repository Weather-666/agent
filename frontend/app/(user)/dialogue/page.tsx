'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Select } from 'antd';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useI18n } from '@/lib/i18n';
import { useToast } from '@/lib/toast';
import {
  CHAT_SESSIONS_CHANGED_EVENT,
  cancelChatTurn,
  createChatSession,
  dispatchChatSessionTitleHint,
  getCreateChatTurnUrl,
  getChatSession,
  getChatSessionMessages,
  getChatTurnEventsUrl,
  submitChatPermission,
} from '@/lib/api/chat';
import { refreshToken } from '@/lib/api/auth';
import { clearAuthState, getAccessToken, getRefreshToken, saveAuthTokens, getTenantId } from '@/lib/request';
import { bindSessionExpert, getSessionExpert, updateSessionExpert } from '@/lib/session-expert';
import {
  getExpertMarketCategories,
  getExpertMarketExperts,
  type ExpertMarketCategory,
  type ExpertMarketExpert,
} from '@/lib/api/expert-market';
import { ChatAttachmentChips, MessageAttachmentList, useChatAttachments, type MessageAttachment } from '@/lib/chat-attachments';
import {
  DEFAULT_EXPERT_SELECTION_ID,
  createDefaultExpertCard,
  isDefaultExpertSelection,
  type ExpertSelectionCard,
} from '@/lib/default-expert';
import { useLibraryMention } from '@/lib/library-mention';
import {
  buildToolTraceItem,
  expertTitleKeys,
  findTraceIndex,
  getMessageList,
  getSessionId,
  isTracePlaceholder,
  localizeStatus,
  mergeTraceText,
  normalizeHistoryMessage,
  normalizeMarkdownForDisplay,
  normalizeTraceText,
  parseSseJson,
  parseSseMessage,
  plainAssistantMessage,
  readErrorMessage,
  readSourceCount,
  readSources,
  readTextDelta,
  readToolProgress,
  readTraceText,
  StreamEofError,
  StreamTimeoutError,
  STREAM_IDLE_TIMEOUT_MS,
  unwrapCreatedSession,
  type AddFeatureKey,
  type AssistantTraceItem,
  type ChatMessage,
  type CitationSource,
  type TurnSnapshotData,
} from './_stream';

const allCategoryId = 'all';

type ExpertCategoryOption = {
  key: string;
  label: string;
};

function toExpertShort(name: string) {
  const normalized = name.trim();
  if (!normalized) return 'E';
  const first = normalized[0];
  if (/^[a-z]$/i.test(first)) return first.toUpperCase();
  return first;
}

function toExpertCard(expert: ExpertMarketExpert, locale: string): ExpertSelectionCard {
  const content = expert.localizedContent?.[locale === 'zh-CN' ? 'zh' : 'en'];
  const title = content?.name?.trim() || expert.name?.trim() || 'Unnamed expert';
  const starter = expert.guideQuestions?.find((q) => typeof q === 'string' && q.trim()) || '';
  return {
    id: expert.id,
    categoryId: expert.categoryId || 'uncategorized',
    categoryName: content?.categoryName?.trim() || expert.categoryName?.trim() || 'Uncategorized',
    short: toExpertShort(title),
    title,
    description: content?.abilityIntro?.trim() || expert.abilityIntro?.trim() || 'No expert profile yet.',
    starter: starter || `Ask ${title} to analyze an Amazon operations issue.`,
    isAccessible: expert.isAccessible,
  };
}

function toCategoryOptions(experts: ExpertSelectionCard[], categories: ExpertMarketCategory[]): ExpertCategoryOption[] {
  const options = new Map<string, string>();
  categories.forEach((category) => {
    if (category.id && category.name) options.set(category.id, category.name);
  });
  experts.forEach((expert) => {
    if (expert.categoryId && expert.categoryName) options.set(expert.categoryId, expert.categoryName);
  });
  return [{ key: allCategoryId, label: 'All' }, ...Array.from(options, ([key, label]) => ({ key, label }))];
}

function PaperclipIcon({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21.4 11.6 12 21a6 6 0 0 1-8.5-8.5l9.7-9.7a4 4 0 0 1 5.7 5.7l-9.8 9.8a2 2 0 0 1-2.8-2.8l8.6-8.6" />
    </svg>
  );
}

function GlobeIcon({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM3.6 9h16.8M3.6 15h16.8M12 3c2.2 2.4 3.3 5.4 3.3 9S14.2 18.6 12 21c-2.2-2.4-3.3-5.4-3.3-9S9.8 5.4 12 3Z" />
    </svg>
  );
}

function BookOpenIcon({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 6c-1.7-1.4-3.8-2-6.3-2H4v14h1.7c2.4 0 4.6.6 6.3 2 1.7-1.4 3.8-2 6.3-2H20V4h-1.7c-2.5 0-4.6.6-6.3 2Z" />
      <path d="M12 6v14M7.5 8.5h2M14.5 8.5h2" />
    </svg>
  );
}

function SourceBadge({ count }: { count: number }) {
  const { t } = useI18n();
  if (count <= 0) return null;

  return (
    <div className="read-summary">
      <span>{t("userPages.dialogue.sourceRead", { count })}</span>
    </div>
  );
}

function SourcePill({ count, sources }: { count: number; sources?: CitationSource[] }) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  if (count <= 0) return null;

  const fileNames = (sources ?? []).map((source) => source.fileName).filter(Boolean);

  return (
    <div className="source-pill">
      <button
        type="button"
        className="source-pill-toggle"
        onClick={() => setExpanded((current) => !current)}
        aria-expanded={expanded}
      >
        <span>{t("userPages.dialogue.sourceCount", { count })}</span>
      </button>
      {expanded && fileNames.length ? (
        <ul className="source-pill-list">
          {fileNames.map((fileName, index) => (
            <li key={`${fileName}-${index}`} className="source-pill-item">{fileName}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function AssistantTrace({ items, autoOpen = false, isActive = false }: { items: AssistantTraceItem[]; autoOpen?: boolean; isActive?: boolean }) {
  const { t } = useI18n();
  if (!items.length) return null;
  const visibleItems = items
    .map((item) => ({ ...item, text: normalizeTraceText(item.text) }))
    .filter((item) => item.text && !isTracePlaceholder(item.text));
  if (!visibleItems.length) return null;

  return (
    <details className="assistant-trace" open={autoOpen}>
      <summary>
        <span>{t("userPages.dialogue.traceTitle")}</span>
        {isActive ? <span className="assistant-trace-spinner" aria-label={t("userPages.dialogue.thinkingLabel")} /> : null}
      </summary>
      <div className="assistant-trace-list">
        {visibleItems.map((item, index) => (
          <div key={`${item.kind}-${index}`} className="assistant-trace-item">
            <span>{localizeStatus(item.text, t)}</span>
          </div>
        ))}
      </div>
    </details>
  );
}

function AssistantActions({ answerText, onRetry }: { answerText: string; onRetry?: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    if (!answerText) return;
    let copySucceeded = false;

    try {
      await navigator.clipboard.writeText(answerText);
      copySucceeded = true;
    } catch {
      try {
        const textarea = document.createElement('textarea');
        textarea.value = answerText;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        const copied = document.execCommand('copy');
        document.body.removeChild(textarea);
        copySucceeded = copied;
      } catch {
        copySucceeded = false;
      }
    }

    if (!copySucceeded) {
      toast.error(t("userPages.dialogue.copyFailed"));
      return;
    }

    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  return (
    <div className="answer-actions" aria-label={t("userPages.dialogue.answerActions")}>
      <button
        type="button"
        title={copied ? t("userPages.dialogue.copied") : t("userPages.dialogue.copy")}
        onClick={() => void handleCopy()}
      >
        {copied ? (
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M20 6 9 17l-5-5" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M8 8h11v11H8zM5 16H4a1 1 0 0 1-1-1V5a2 2 0 0 1 2-2h10a1 1 0 0 1 1 1v1" />
          </svg>
        )}
      </button>
      <button type="button" title={t("userPages.dialogue.retry")} onClick={onRetry} disabled={!onRetry}>
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v6h-6" />
        </svg>
      </button>
    </div>
  );
}


export default function DialoguePage() {
  const { t, locale } = useI18n();
  const router = useRouter();
  const searchParams = useSearchParams();
  const chat = searchParams.get('chat') ?? '';
  const expert = searchParams.get('expert') ?? '';
  const expertName = searchParams.get('expertName') ?? '';

  // First-turn data is passed via sessionStorage (not URL) to avoid 431 on long inputs.
  // Read and clear it once at mount so refresh cannot re-submit the same question.
  const [pendingFirstTurn] = useState<{ text: string; webSearchEnabled: boolean; attachments: string[] } | null>(() => {
    if (typeof window === 'undefined' || chat) return null;
    try {
      const raw = sessionStorage.getItem('winwise.pending-first-turn.v1');
      if (!raw) return null;
      sessionStorage.removeItem('winwise.pending-first-turn.v1');
      const parsed = JSON.parse(raw) as { text?: unknown; webSearchEnabled?: unknown; attachments?: unknown };
      if (typeof parsed.text !== 'string') return null;
      return {
        text: parsed.text,
        webSearchEnabled: Boolean(parsed.webSearchEnabled),
        attachments: Array.isArray(parsed.attachments)
          ? parsed.attachments.filter((id): id is string => typeof id === 'string')
          : [],
      };
    } catch {
      return null;
    }
  });

  const [extraMessages, setExtraMessages] = useState<ChatMessage[]>([]);
  const [prompt, setPrompt] = useState('');
  const initialExpertId = expert || DEFAULT_EXPERT_SELECTION_ID;
  const [activeExpertTitle, setActiveExpertTitle] = useState(
    expertName || (isDefaultExpertSelection(initialExpertId) ? t('home.defaultExpertTitle') : ''),
  );
  const [activeExpertId, setActiveExpertId] = useState(initialExpertId);
  const [isExpertsPopoverOpen, setIsExpertsPopoverOpen] = useState(false);
  const [activeExpertCategory, setActiveExpertCategory] = useState(allCategoryId);
  const [marketExpertCards, setMarketExpertCards] = useState<ExpertSelectionCard[]>([]);
  const [marketCategories, setMarketCategories] = useState<ExpertMarketCategory[]>([]);
  const [isExpertsLoading, setIsExpertsLoading] = useState(true);
  const [expertsError, setExpertsError] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState('');
  const [pendingPermission, setPendingPermission] = useState<{ permissionId: string; data: unknown } | null>(null);
  const [addFeatureState, setAddFeatureState] = useState<Record<AddFeatureKey, boolean>>({
    webSearch: pendingFirstTurn?.webSearchEnabled ?? false,
  });
  const { attachments, addFiles, addLibraryFile, removeAttachment, clearAttachments, readyFileIds } = useChatAttachments(
    (kind) =>
      setError(
        kind === 'auth'
          ? t("userPages.dialogue.authExpired")
          : kind === 'tooLarge'
          ? t("userPages.dialogue.attachmentTooLarge")
          : t("userPages.dialogue.attachmentUploadFailed"),
      ),
  );
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const messagesRef = useRef<HTMLElement | null>(null);
  const expertsTriggerRef = useRef<HTMLButtonElement | null>(null);
  const expertsPopoverRef = useRef<HTMLDivElement | null>(null);
  // Whether the viewport is pinned to the bottom. Stays true while the user is
  // at (or near) the latest content, so streaming output keeps following; flips
  // to false the moment the user scrolls up to read history.
  const stickToBottomRef = useRef(true);
  const mention = useLibraryMention({
    value: prompt,
    onChange: setPrompt,
    textareaRef,
    onSelect: addLibraryFile,
    excludeIds: readyFileIds,
  });
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const currentTurnIdRef = useRef<string>('');
  const stopRequestedRef = useRef(false);
  const pendingSessionSwitchRef = useRef('');
  const autoSubmittedPromptRef = useRef('');
  const sendQuestionRef = useRef<
    ((
      text: string,
      options: {
        appendUserMessage: boolean;
        clearPrompt: boolean;
        webSearchEnabled?: boolean;
        attachmentFileIds?: string[];
      },
    ) => Promise<void>) | null
  >(null);

  const defaultExpertCard = useMemo(() => createDefaultExpertCard({
    title: t('home.defaultExpertTitle'),
    categoryName: t('home.defaultExpertCategory'),
    description: t('home.defaultExpertDescription'),
    starter: t('home.defaultExpertStarter'),
  }), [t]);
  const expertCards = useMemo(
    () => [defaultExpertCard, ...marketExpertCards.filter((card) => card.id !== DEFAULT_EXPERT_SELECTION_ID)],
    [defaultExpertCard, marketExpertCards],
  );
  const expertCategories = useMemo(
    () => toCategoryOptions(expertCards, marketCategories),
    [expertCards, marketCategories],
  );

  const chatMessages = extraMessages;

  useEffect(() => {
    let ignore = false;

    queueMicrotask(() => {
      if (!ignore) {
        setError('');
        setPrompt('');
      }
    });

    if (pendingSessionSwitchRef.current === chat) {
      pendingSessionSwitchRef.current = '';

      return () => {
        ignore = true;
      };
    }

    streamAbortRef.current?.abort();

    if (!chat) {
      if (pendingFirstTurn) {
        return () => {
          ignore = true;
        };
      }

      queueMicrotask(() => {
        if (!ignore) {
          setExtraMessages([]);
          setIsSending(false);
        }
      });

      return () => {
        ignore = true;
      };
    }

    queueMicrotask(() => {
      if (!ignore) setIsSending(true);
    });

    getChatSessionMessages(chat)
      .then((response) => {
        if (ignore) return;

        const rawMessages = getMessageList(response);
        const messages = rawMessages.flatMap((message) => normalizeHistoryMessage(message));
        setExtraMessages(messages);

        // Resume any turns that were still running when we left the page.
        const sessionId = chat;
        rawMessages.forEach((message, rawIdx) => {
          const status = String(message.status || '').toLowerCase();
          const turnId = message.turnId || (typeof message.id === 'string' ? message.id : '');
          if (status !== 'running' || !turnId) return;

          // Find the assistant message index in the normalized list
          let assistantMsgIndex = -1;
          let cursor = 0;
          for (let i = 0; i < rawIdx; i++) {
            cursor += normalizeHistoryMessage(rawMessages[i]).length;
          }
          const normalized = normalizeHistoryMessage(message);
          for (let k = 0; k < normalized.length; k++) {
            if (normalized[k].role === 'assistant') {
              assistantMsgIndex = cursor + k;
              break;
            }
          }
          if (assistantMsgIndex < 0) return;

          setIsSending(true);
          resumeTurnEvents(turnId, assistantMsgIndex, sessionId)
            .catch(() => {
              // Failed to resume — re-fetch messages to get actual state
              getChatSessionMessages(sessionId)
                .then((r) => {
                  if (ignore) return;
                  setExtraMessages(getMessageList(r).flatMap(normalizeHistoryMessage));
                })
                .catch(() => {});
            })
            .finally(() => {
              if (!ignore) {
                currentTurnIdRef.current = '';
                setIsSending(false);
              }
            });
        });
      })
      .catch(() => {
        if (!ignore) {
          setExtraMessages([]);
          setError(t("userPages.dialogue.loadHistoryFailed"));
        }
      })
      .finally(() => {
        if (!ignore) setIsSending(false);
      });

    return () => {
      ignore = true;
    };
  }, [chat, pendingFirstTurn, t]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = '0px';
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, [prompt]);

  // Track whether the user is at the bottom. Once they scroll up we stop
  // auto-following so reading history isn't interrupted; scrolling back to the
  // bottom re-arms it.
  useEffect(() => {
    const container = messagesRef.current;
    if (!container) return;

    const onScroll = () => {
      const distanceFromBottom =
        container.scrollHeight - container.scrollTop - container.clientHeight;
      stickToBottomRef.current = distanceFromBottom <= 80;
    };

    container.addEventListener('scroll', onScroll, { passive: true });
    return () => container.removeEventListener('scroll', onScroll);
  }, []);

  // Follow new content to the bottom on every growth (streamed tokens, new
  // messages, trace updates) — but only while pinned to the bottom.
  useEffect(() => {
    const container = messagesRef.current;
    if (!container || !stickToBottomRef.current) return;
    container.scrollTop = container.scrollHeight;
  }, [chatMessages, isSending]);

  useEffect(() => {
    if (!expert || pendingFirstTurn) return;

    queueMicrotask(() => {
      setActiveExpertTitle(expertName || (expert && expertTitleKeys[expert] ? t(expertTitleKeys[expert]) : '') || '');
    });
  }, [expert, expertName, pendingFirstTurn, t]);

  // On reload of an existing session the URL no longer carries the expert.
  // Use localStorage as an immediate placeholder, then override with the API response.
  useEffect(() => {
    if (!chat) return;
    let ignore = false;

    const bound = getSessionExpert(chat);
    if (bound?.name) {
      queueMicrotask(() => {
        if (!ignore) {
          setActiveExpertTitle(bound.name);
          setActiveExpertId(bound.id);
        }
      });
    }

    getChatSession(chat)
      .then((session) => {
        if (ignore) return;
        const apiExpertId = typeof session?.expertId === 'string' ? session.expertId.trim() : '';
        const resolvedExpertId = apiExpertId || DEFAULT_EXPERT_SELECTION_ID;
        const resolvedTitle = apiExpertId
          ? (bound?.id === apiExpertId ? bound.name : '')
          : t('home.defaultExpertTitle');
        setActiveExpertId(resolvedExpertId);
        if (resolvedTitle) setActiveExpertTitle(resolvedTitle);
        updateSessionExpert(chat, { id: resolvedExpertId, name: resolvedTitle });
      })
      .catch(() => { /* silent: keep localStorage placeholder */ });

    return () => { ignore = true; };
  }, [chat, t]);

  useEffect(() => {
    let ignore = false;

    Promise.allSettled([getExpertMarketExperts(), getExpertMarketCategories()])
      .then(([expertsResult, categoriesResult]) => {
        if (ignore) return;

        const experts =
          expertsResult.status === 'fulfilled'
            ? (Array.isArray(expertsResult.value?.items) ? expertsResult.value.items : []).map((item) => toExpertCard(item, locale))
            : [];
        const categories =
          categoriesResult.status === 'fulfilled'
            ? Array.isArray(categoriesResult.value?.items)
              ? categoriesResult.value.items
              : []
            : [];

        setMarketExpertCards(experts);
        setMarketCategories(categories);
        setExpertsError(expertsResult.status === 'rejected' ? t('home.publishedExpertsLoadFailed') : '');
      })
      .finally(() => {
        if (!ignore) setIsExpertsLoading(false);
      });

    return () => {
      ignore = true;
    };
  }, [locale, t]);

  // When the session has a known expertId but no display title yet, resolve the title
  // from the expert market cards. This covers historical sessions where the URL has no
  // expert param and localStorage may have no entry (different browser / cleared storage).
  useEffect(() => {
    if (!activeExpertId || !expertCards.length) return;
    const card = expertCards.find((c) => c.id === activeExpertId);
    if (!card?.title) return;
    let ignore = false;
    queueMicrotask(() => {
      if (ignore) return;
      setActiveExpertTitle((current) => current || card.title);
      // Persist the resolved name so future reloads don't need another lookup.
      if (chat) updateSessionExpert(chat, { id: activeExpertId, name: card.title });
    });
    return () => {
      ignore = true;
    };
  }, [activeExpertId, expertCards, chat]);

  useEffect(() => {
    if (expertCategories.some((category) => category.key === activeExpertCategory)) return;
    queueMicrotask(() => setActiveExpertCategory(allCategoryId));
  }, [activeExpertCategory, expertCategories]);

  useEffect(() => {
    if (!isExpertsPopoverOpen) return;

    function handleDocumentPointerDown(event: PointerEvent) {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (expertsTriggerRef.current?.contains(target)) return;
      if (expertsPopoverRef.current?.contains(target)) return;
      if (target instanceof Element && target.closest('.ant-select-dropdown')) return;
      setIsExpertsPopoverOpen(false);
    }

    document.addEventListener('pointerdown', handleDocumentPointerDown);
    return () => {
      document.removeEventListener('pointerdown', handleDocumentPointerDown);
    };
  }, [isExpertsPopoverOpen]);

  const selectedExpertLabel = activeExpertTitle || t('home.defaultExpertTitle');

  const filteredExpertCards = useMemo(() => {
    if (activeExpertCategory === allCategoryId) return expertCards;
    return expertCards.filter((item) => item.categoryId === activeExpertCategory);
  }, [activeExpertCategory, expertCards]);

  function selectExpert(expertCard: ExpertSelectionCard) {
    if (chat || isSending) return; // locked once session exists or is being created
    setActiveExpertTitle(expertCard.title);
    setActiveExpertId(expertCard.id);
    setIsExpertsPopoverOpen(false);
  }

  function toggleAddFeature(feature: AddFeatureKey) {
    setAddFeatureState((current) => ({ ...current, [feature]: !current[feature] }));
  }

  const handleAttachmentSelect = (fileList: FileList | null) => {
    addFiles(fileList);
    // Reset so selecting the same file again re-triggers onChange.
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  useEffect(() => {
    return () => {
      streamAbortRef.current?.abort();
    };
  }, []);

  const updateAssistantMessage = (
    index: number,
    text: string,
    sourceCount?: number,
    isError?: boolean,
    isStopped?: boolean,
    sources?: CitationSource[],
  ) => {
    // Render the streamed answer as-is. Reasoning/tool trace arrives separately via onTrace,
    // so we never re-parse the answer text to extract "process" lines (that dropped content).
    setExtraMessages((prev) =>
      prev.map((message, messageIndex) => {
        if (messageIndex !== index || message.role !== 'assistant') return message;

        return {
          ...message,
          sourceCount: sourceCount ?? message.sourceCount,
          sources: sources ?? message.sources,
          markdown: normalizeMarkdownForDisplay(text || '正在思考...'),
          ...(isError !== undefined ? { isError } : {}),
          ...(isStopped !== undefined ? { isStopped } : {}),
        };
      }),
    );
  };

  // Drop the "正在连接智能体" placeholder once the turn has actually started
  // producing output. Plain Q&A turns emit no reasoning/tool trace events, so
  // without this the trace panel would stay stuck on the initial status even
  // after the answer streams in and the turn completes.
  const clearInitialTraceStatus = (index: number) => {
    setExtraMessages((prev) =>
      prev.map((message, messageIndex) => {
        if (messageIndex !== index || message.role !== 'assistant') return message;
        if (!message.traceItems.some((trace) => trace.id === 'status:initial')) return message;

        return {
          ...message,
          traceItems: message.traceItems.filter((trace) => trace.id !== 'status:initial'),
        };
      }),
    );
  };

  const appendAssistantTraceDelta = (index: number, item: AssistantTraceItem) => {
    if (!item.text) return;

    setExtraMessages((prev) =>
      prev.map((message, messageIndex) => {
        if (messageIndex !== index || message.role !== 'assistant') return message;

        const traceItems = message.traceItems.filter((trace) => trace.id !== 'status:initial');
        const lastIndex = findTraceIndex(traceItems, item);
        const last = lastIndex >= 0 ? traceItems[lastIndex] : undefined;

        if (last) {
          traceItems[lastIndex] = { ...last, ...item, text: item.id ? item.text.trim() : mergeTraceText(last.text, item.text) };
        } else {
          traceItems.push({ ...item, text: item.text.trim() });
        }

        return {
          ...message,
          traceItems,
        };
      }),
    );
  };

  // Apply a turn_snapshot or turn_state to the message at index.
  // isFinal=true means turn_state (definitive end), isFinal=false means turn_snapshot (intermediate).
  const applyTurnSnapshot = (
    index: number,
    snapshot: TurnSnapshotData,
    isFinal: boolean,
    currentAnswer: string,
    currentSources: CitationSource[],
  ) => {
    const responseText = snapshot.responseText ?? null;
    const status = String(snapshot.status || '').toLowerCase();
    const errorMessage = snapshot.errorMessage ?? null;
    const eventSeq = typeof snapshot.eventSeq === 'number' ? snapshot.eventSeq : undefined;

    setExtraMessages((prev) =>
      prev.map((message, messageIndex) => {
        if (messageIndex !== index || message.role !== 'assistant') return message;

        const hasResponseText = responseText && responseText.trim();
        const hasCurrentAnswer = currentAnswer && currentAnswer.trim();

        const turnAttachments = Array.isArray(snapshot.attachments) && snapshot.attachments.length
          ? snapshot.attachments
          : message.turnAttachments;

        // Mirror normalizeHistoryMessage: failed with no content → isError (red bubble);
        // failed with content → isFailed (partial answer + error footer).
        let markdown: string;
        let isError = false;
        let isFailed = false;
        let isStopped = false;
        let errorText: string | undefined;

        if (isFinal && status === 'failed') {
          if (hasResponseText) {
            markdown = normalizeMarkdownForDisplay(responseText!);
            isFailed = true;
            errorText = errorMessage ?? undefined;
          } else if (hasCurrentAnswer) {
            markdown = normalizeMarkdownForDisplay(currentAnswer);
            isFailed = true;
            errorText = errorMessage ?? undefined;
          } else {
            markdown = errorMessage || '问答失败';
            isError = true;
          }
        } else if (isFinal && status === 'cancelled') {
          isStopped = true;
          markdown = hasResponseText
            ? normalizeMarkdownForDisplay(responseText!)
            : hasCurrentAnswer
            ? normalizeMarkdownForDisplay(currentAnswer)
            : message.markdown;
        } else {
          markdown = hasResponseText
            ? normalizeMarkdownForDisplay(responseText!)
            : hasCurrentAnswer
            ? normalizeMarkdownForDisplay(currentAnswer)
            : message.markdown;
        }

        return {
          ...message,
          markdown,
          eventSeq,
          isStreaming: !isFinal,
          turnAttachments,
          isError,
          isFailed,
          isStopped,
          errorText,
        };
      }),
    );
  };

  // Internal SSE read loop shared between POST (new turn) and GET (resume/recover).
  const readSseStream = async (
    reader: ReadableStreamDefaultReader<Uint8Array>,
    abortController: AbortController,
    sessionId: string,
    onToken: (text: string) => void,
    onSourceCount: (count: number) => void,
    onSources: (sources: CitationSource[]) => void,
    onTrace: (item: AssistantTraceItem) => void,
    onActive: () => void,
    onClearInitial: () => void,
    onPermissionRequired: (p: { permissionId: string; data: unknown }) => void,
    onTurnStarted: (turnId: string) => void,
    onSnapshot: (data: TurnSnapshotData, isFinal: boolean) => void,
    onStreamError: (message: string) => void,
    afterEventSeq?: number,
  ) => {
    const decoder = new TextDecoder();
    let buffer = '';
    let terminalReached = false;

    while (true) {
      let idleTimer: ReturnType<typeof setTimeout> | null = null;
      const readResult = await Promise.race([
        reader.read(),
        new Promise<never>((_, reject) => {
          idleTimer = setTimeout(() => {
            abortController.abort();
            reject(new StreamTimeoutError());
          }, STREAM_IDLE_TIMEOUT_MS);
        }),
      ]);
      if (idleTimer) clearTimeout(idleTimer);

      const { done, value } = readResult;
      if (done) break;

      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');

      let boundary = buffer.indexOf('\n\n');
      while (boundary >= 0) {
        const raw = buffer.slice(0, boundary).trim();
        buffer = buffer.slice(boundary + 2);

        if (raw) {
          const { id: eventId, event, data } = parseSseMessage(raw);
          const parsed = parseSseJson(data);

          // Skip events already applied when resuming with cursor
          if (typeof afterEventSeq === 'number' && typeof eventId === 'number' && eventId <= afterEventSeq) {
            boundary = buffer.indexOf('\n\n');
            continue;
          }

          const isActiveEvent =
            event === 'turn_started' ||
            event === 'message_delta' ||
            event === 'token' ||
            event === 'delta' ||
            event === 'reasoning_delta' ||
            event === 'session_usage_update';

          if (isActiveEvent) {
            onActive();
          }

          if (event === 'turn_started') {
            const turnId = typeof parsed?.turnId === 'string' ? parsed.turnId : '';
            if (turnId) onTurnStarted(turnId);
          }

          if (event === 'token' || event === 'message_delta' || event === 'delta') {
            const token = readTextDelta(parsed);
            if (token) {
              onClearInitial();
              onToken(token);
            }
          }

          if (event === 'reasoning_delta' || event === 'reasoning' || event === 'thinking' || event === 'thought') {
            const text = readTraceText(parsed);
            if (text) onTrace({ kind: 'thinking', text });
          }

          if (event === 'tool_call_update') {
            const item = readToolProgress(parsed);
            if (item) onTrace(item);
          }

          if (event === 'tool_call' || event === 'tool_result') {
            onTrace(buildToolTraceItem(parsed, event === 'tool_result'));
          }

          if (event === 'permission' || event === 'permission_required') {
            const permissionId = typeof parsed?.permissionId === 'string' ? parsed.permissionId : null;
            const permissionData = parsed?.data ?? null;
            onTrace({ kind: 'action', text: '正在等待操作确认', id: permissionId ?? undefined });
            if (permissionId) onPermissionRequired({ permissionId, data: permissionData });
          }

          if (event === 'retrieval' || event === 'citation' || event === 'sources') {
            const count = readSourceCount(parsed);
            if (typeof count === 'number') onSourceCount(count);
            const sources = readSources(parsed);
            if (sources.length) onSources(sources);
            const text = readTraceText(parsed);
            if (text) onTrace({ kind: 'action', text });
          }

          if (event === 'session_title_updated') {
            const title = typeof parsed?.title === 'string' ? parsed.title.trim() : '';
            if (title) dispatchChatSessionTitleHint(sessionId, title);
          }

          // turn_snapshot: full state snapshot (for resume), continue streaming
          if (event === 'turn_snapshot') {
            const snapshot = parsed as TurnSnapshotData | null;
            if (snapshot) onSnapshot(snapshot, false);
          }

          // turn_state: authoritative final state — apply and end stream
          if (event === 'turn_state') {
            terminalReached = true;
            onClearInitial();
            const snapshot = parsed as TurnSnapshotData | null;
            if (snapshot) onSnapshot(snapshot, true);
            return;
          }

          // error / turn_failed: note it but keep reading for turn_state
          if (event === 'error' || event === 'turn_failed') {
            onStreamError(readErrorMessage(parsed) || t("userPages.dialogue.generationFailed"));
            // Don't throw — continue reading for turn_state
          }

          // turn_completed / cancelled / stop: continue reading for turn_state
          if (event === 'stop' || event === 'cancelled' || event === 'turn_completed') {
            terminalReached = true;
            onClearInitial();
            // Don't return — keep reading for turn_state which carries final content
          }
        }

        boundary = buffer.indexOf('\n\n');
      }
    }

    if (!terminalReached) {
      throw new StreamEofError();
    }
  };

  const streamChatTurn = async (
    sessionId: string,
    question: string,
    webSearchEnabled: boolean,
    attachmentFileIds: string[],
    onToken: (text: string) => void,
    onSourceCount: (count: number) => void,
    onSources: (sources: CitationSource[]) => void,
    onTrace: (item: AssistantTraceItem) => void,
    onActive: () => void,
    onClearInitial: () => void,
    onPermissionRequired: (p: { permissionId: string; data: unknown }) => void,
    onTurnStarted: (turnId: string) => void,
    onSnapshot: (data: TurnSnapshotData, isFinal: boolean) => void,
    onStreamError: (message: string) => void,
  ) => {
    const abortController = new AbortController();
    streamAbortRef.current = abortController;

    const doFetch = (token: string) =>
      fetch(getCreateChatTurnUrl(sessionId), {
        method: 'POST',
        headers: {
          Accept: 'text/event-stream',
          'Content-Type': 'application/json',
          'X-Tenant-ID': getTenantId(),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          question,
          webSearchEnabled,
          ...(attachmentFileIds.length > 0 ? { attachmentFileIds } : {}),
        }),
        signal: abortController.signal,
      });

    let response = await doFetch(getAccessToken());

    if (response.status === 401) {
      const rt = getRefreshToken();
      if (rt) {
        try {
          const tokens = await refreshToken({ refreshToken: rt });
          saveAuthTokens(tokens);
          response = await doFetch(tokens.accessToken);
        } catch {
          clearAuthState({ notify: true });
          throw Object.assign(new Error(t("userPages.dialogue.authExpired")), { status: 401 });
        }
      } else {
        clearAuthState({ notify: true });
        throw Object.assign(new Error(t("userPages.dialogue.authExpired")), { status: 401 });
      }
    }

    if (!response.ok || !response.body) {
      if (response.status === 401) {
        clearAuthState({ notify: true });
        throw Object.assign(new Error(t("userPages.dialogue.authExpired")), { status: 401 });
      }
      let errMessage = t("userPages.dialogue.requestFailed");
      try {
        const errJson = await response.json() as { message?: string; code?: string };
        if (errJson?.message) errMessage = errJson.message;
      } catch { /* ignore */ }
      if (response.status === 402) {
        errMessage = errMessage || t("userPages.dialogue.creditExhausted");
      } else if (response.status === 403) {
        errMessage = errMessage || t("userPages.dialogue.expertNotIncluded");
      } else if (response.status === 409) {
        errMessage = errMessage || t("userPages.dialogue.planCreditRequired");
      }
      throw Object.assign(new Error(errMessage), { status: response.status });
    }

    await readSseStream(
      response.body.getReader(),
      abortController,
      sessionId,
      onToken,
      onSourceCount,
      onSources,
      onTrace,
      onActive,
      onClearInitial,
      onPermissionRequired,
      onTurnStarted,
      onSnapshot,
      onStreamError,
    );
  };

  // Resume a running turn by subscribing to GET events (no cursor = turn_snapshot first).
  const resumeTurnEvents = async (
    turnId: string,
    messageIndex: number,
    sessionId: string,
    afterEventSeq?: number,
  ) => {
    const abortController = new AbortController();
    streamAbortRef.current = abortController;
    currentTurnIdRef.current = turnId;

    const url = getChatTurnEventsUrl(turnId, afterEventSeq);
    const token = getAccessToken();
    const response = await fetch(url, {
      method: 'GET',
      headers: {
        Accept: 'text/event-stream',
        'X-Tenant-ID': getTenantId(),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      signal: abortController.signal,
    });

    if (!response.ok || !response.body) {
      // Non-fatal: just keep what we have
      return;
    }

    let answer = '';
    let latestSourceCount = 0;
    let latestSources: CitationSource[] = [];

    await readSseStream(
      response.body.getReader(),
      abortController,
      sessionId,
      (token) => {
        answer += token;
        updateAssistantMessage(messageIndex, answer, latestSourceCount, undefined, undefined, latestSources);
      },
      (count) => {
        latestSourceCount = count;
        updateAssistantMessage(messageIndex, answer, latestSourceCount, undefined, undefined, latestSources);
      },
      (sources) => {
        latestSources = sources;
        updateAssistantMessage(messageIndex, answer, latestSourceCount, undefined, undefined, latestSources);
      },
      (item) => appendAssistantTraceDelta(messageIndex, item),
      () => setError(''),
      () => clearInitialTraceStatus(messageIndex),
      (p) => setPendingPermission(p),
      (tId) => { currentTurnIdRef.current = tId; },
      (snapshot, isFinal) => applyTurnSnapshot(messageIndex, snapshot, isFinal, answer, latestSources),
      (msg) => {
        // Stream error during resume — show but don't discard partial content
        setError(msg);
      },
      afterEventSeq,
    );
  };

  const ensureSessionId = async (firstMessage: string) => {
    if (chat) return chat;
    if (!getAccessToken()) throw new Error(t("userPages.dialogue.loginRequired"));

    // Persist a title derived from the first message at creation time so it survives a reload
    // (the backend stores it and returns it in the session list). The session_title_updated
    // stream event can still refine this title live; the optimistic hint mirrors it in the sidebar.
    const initialTitle = firstMessage.slice(0, 30) || t("userPages.dialogue.newChat");
    const requestedExpertId = isDefaultExpertSelection(activeExpertId) ? '' : activeExpertId;
    const createdSession = unwrapCreatedSession(await createChatSession({
      title: initialTitle,
      ...(requestedExpertId ? { expertId: requestedExpertId } : {}),
    }));
    const sessionId = getSessionId(createdSession);
    if (!sessionId) throw new Error(t("userPages.dialogue.createSessionFailed"));

    // A null expertId is the Backend's default ACP route, represented by a UI-only sentinel.
    const returnedExpertId =
      createdSession && typeof (createdSession as { expertId?: unknown }).expertId === 'string'
        ? (createdSession as { expertId: string }).expertId
        : '';
    const boundExpertId = returnedExpertId || requestedExpertId || DEFAULT_EXPERT_SELECTION_ID;
    const boundExpertTitle = isDefaultExpertSelection(boundExpertId)
      ? t('home.defaultExpertTitle')
      : boundExpertId === activeExpertId
        ? activeExpertTitle
        : '';
    bindSessionExpert(sessionId, { id: boundExpertId, name: boundExpertTitle });
    if (boundExpertId !== activeExpertId) setActiveExpertId(boundExpertId);
    if (boundExpertTitle) setActiveExpertTitle(boundExpertTitle);

    pendingSessionSwitchRef.current = sessionId;
    window.dispatchEvent(new Event(CHAT_SESSIONS_CHANGED_EVENT));
    dispatchChatSessionTitleHint(sessionId, initialTitle);
    router.replace(`/dialogue?chat=${encodeURIComponent(sessionId)}`, { scroll: false });

    return sessionId;
  };

  const sendQuestion = async (
    text: string,
    {
      appendUserMessage,
      clearPrompt,
      webSearchEnabled = addFeatureState.webSearch,
      attachmentFileIds,
    }: {
      appendUserMessage: boolean;
      clearPrompt: boolean;
      webSearchEnabled?: boolean;
      attachmentFileIds?: string[];
    },
  ) => {
    const turnReady = attachmentFileIds ?? readyFileIds;
    if ((!text.trim() && turnReady.length === 0) || isSending) return;
    streamAbortRef.current?.abort();
    setError('');
    if (clearPrompt) setPrompt('');
    setIsSending(true);
    // A fresh send always jumps to the bottom so the new question is visible,
    // regardless of where the user had scrolled to.
    stickToBottomRef.current = true;

    const assistantIndex = extraMessages.length + (appendUserMessage ? 1 : 0);
    const turnAttachmentObjects: MessageAttachment[] = attachmentFileIds
      ? attachmentFileIds.map((id) => ({ fileId: id }))
      : attachments.filter((a) => a.status === 'ready' && a.fileId).map((a) => ({
          fileId: a.fileId,
          name: a.name,
          mimeType: a.mimeType,
          sizeLabel: a.sizeLabel,
          previewUrl: a.previewUrl,
        }));
    setExtraMessages((prev) => [
      ...prev,
      ...(appendUserMessage
        ? [{ role: 'user' as const, text, attachments: turnAttachmentObjects.length ? turnAttachmentObjects : undefined }]
        : []),
      plainAssistantMessage(),
    ]);
    // Clear composer attachments immediately (same timing as prompt clear) so
    // they don't persist regardless of whether the stream succeeds or errors.
    if (!attachmentFileIds) clearAttachments();

    let answer = '';
    let latestSourceCount = 0;
    let latestSources: CitationSource[] = [];
    let streamErrorMessage = '';

    // Explicit ids (handed off from the home composer) take precedence over the
    // ids uploaded in this composer.
    const turnAttachmentIds = attachmentFileIds ?? readyFileIds;

    // Declared outside try so the catch block can re-fetch history if needed.
    let sessionId = '';

    try {
      sessionId = await ensureSessionId(text);
      await streamChatTurn(
        sessionId,
        text,
        webSearchEnabled,
        turnAttachmentIds,
        (token) => {
          answer += token;
          updateAssistantMessage(assistantIndex, answer, latestSourceCount, undefined, undefined, latestSources);
        },
        (count) => {
          latestSourceCount = count;
          updateAssistantMessage(assistantIndex, answer, latestSourceCount, undefined, undefined, latestSources);
        },
        (sources) => {
          latestSources = sources;
          updateAssistantMessage(assistantIndex, answer, latestSourceCount, undefined, undefined, latestSources);
        },
        (item) => appendAssistantTraceDelta(assistantIndex, item),
        () => setError(''),
        () => clearInitialTraceStatus(assistantIndex),
        (p) => setPendingPermission(p),
        (turnId) => { currentTurnIdRef.current = turnId; },
        (snapshot, isFinal) => {
          applyTurnSnapshot(assistantIndex, snapshot, isFinal, answer, latestSources);
          // turn_state already updated the bubble — don't also show the error below the composer
          if (isFinal) streamErrorMessage = '';
        },
        (msg) => { streamErrorMessage = msg; },
      );
      // Only show below the composer if turn_state did NOT handle it (no final snapshot applied)
      if (streamErrorMessage) setError(streamErrorMessage);
    } catch (err) {
      const apiError = err as { message?: string; status?: number; name?: string };
      if (apiError.name === 'AbortError' && stopRequestedRef.current) {
        // User clicked stop: re-fetch messages to get actual final status from backend
        const effectiveSessionId = sessionId || chat;
        if (effectiveSessionId) {
          getChatSessionMessages(effectiveSessionId)
            .then((response) => {
              const msgs = getMessageList(response).flatMap(normalizeHistoryMessage);
              setExtraMessages(msgs);
            })
            .catch(() => {
              if (answer) {
                updateAssistantMessage(assistantIndex, answer, latestSourceCount, false, true);
              } else {
                updateAssistantMessage(assistantIndex, '已停止', latestSourceCount, false);
              }
            });
        } else {
          if (answer) {
            updateAssistantMessage(assistantIndex, answer, latestSourceCount, false, true);
          } else {
            updateAssistantMessage(assistantIndex, '已停止', latestSourceCount, false);
          }
        }
      } else {
        const isEof = err instanceof StreamEofError;
        const isTimeout = apiError.name === 'StreamTimeoutError';
        const message =
          isEof || isTimeout
            ? t("userPages.dialogue.connectionInterrupted")
            : apiError.name === 'AbortError'
            ? t("userPages.dialogue.aborted")
            : apiError.status === 401
              ? t("userPages.dialogue.authExpired")
              : apiError.status === 402
              ? (apiError.message || t("userPages.dialogue.creditExhausted"))
              : apiError.status === 403
              ? (apiError.message || t("userPages.dialogue.expertNotIncluded"))
              : apiError.status === 409
              ? (apiError.message || t("userPages.dialogue.planCreditRequired"))
              : apiError.message || t("userPages.dialogue.requestFailed");
        clearInitialTraceStatus(assistantIndex);
        if (answer) {
          updateAssistantMessage(assistantIndex, answer, latestSourceCount);
          setError(message);
        } else {
          updateAssistantMessage(assistantIndex, message, latestSourceCount, true);
        }
        if (clearPrompt) setPrompt(text);
        const effectiveSessionId = sessionId || chat;
        if (effectiveSessionId && (isEof || isTimeout || (typeof apiError.status === 'number' && apiError.status >= 400))) {
          getChatSessionMessages(effectiveSessionId)
            .then((response) => {
              const msgs = getMessageList(response).flatMap(normalizeHistoryMessage);
              setExtraMessages(msgs);
            })
            .catch(() => { /* keep inline error on re-fetch failure */ });
        }
      }
    } finally {
      stopRequestedRef.current = false;
      currentTurnIdRef.current = '';
      setIsSending(false);
      streamAbortRef.current = null;
    }
  };

  const retryQuestion = async (text: string, assistantIndex: number) => {
    if (!text.trim() || isSending) return;

    streamAbortRef.current?.abort();
    setError('');
    setIsSending(true);
    setExtraMessages((prev) =>
      prev.map((message, index) => (index === assistantIndex ? plainAssistantMessage() : message)),
    );

    let answer = '';
    let latestSourceCount = 0;
    let latestSources: CitationSource[] = [];
    let streamErrorMessage = '';
    let sessionId = '';

    try {
      sessionId = await ensureSessionId(text);
      await streamChatTurn(
        sessionId,
        text,
        addFeatureState.webSearch,
        [],
        (token) => {
          answer += token;
          updateAssistantMessage(assistantIndex, answer, latestSourceCount, undefined, undefined, latestSources);
        },
        (count) => {
          latestSourceCount = count;
          updateAssistantMessage(assistantIndex, answer, latestSourceCount, undefined, undefined, latestSources);
        },
        (sources) => {
          latestSources = sources;
          updateAssistantMessage(assistantIndex, answer, latestSourceCount, undefined, undefined, latestSources);
        },
        (item) => appendAssistantTraceDelta(assistantIndex, item),
        () => setError(''),
        () => clearInitialTraceStatus(assistantIndex),
        (p) => setPendingPermission(p),
        (turnId) => { currentTurnIdRef.current = turnId; },
        (snapshot, isFinal) => {
          applyTurnSnapshot(assistantIndex, snapshot, isFinal, answer, latestSources);
          if (isFinal) streamErrorMessage = '';
        },
        (msg) => { streamErrorMessage = msg; },
      );
      if (streamErrorMessage) setError(streamErrorMessage);
    } catch (err) {
      const apiError = err as { message?: string; status?: number; name?: string };
      if (apiError.name === 'AbortError' && stopRequestedRef.current) {
        const effectiveSessionId = sessionId || chat;
        if (effectiveSessionId) {
          getChatSessionMessages(effectiveSessionId)
            .then((response) => {
              const msgs = getMessageList(response).flatMap(normalizeHistoryMessage);
              setExtraMessages(msgs);
            })
            .catch(() => {
              if (answer) {
                updateAssistantMessage(assistantIndex, answer, latestSourceCount, false, true);
              } else {
                updateAssistantMessage(assistantIndex, '已停止', latestSourceCount, false);
              }
            });
        } else {
          if (answer) {
            updateAssistantMessage(assistantIndex, answer, latestSourceCount, false, true);
          } else {
            updateAssistantMessage(assistantIndex, '已停止', latestSourceCount, false);
          }
        }
      } else {
        const isEof = err instanceof StreamEofError;
        const isTimeout = apiError.name === 'StreamTimeoutError';
        const message =
          isEof || isTimeout
            ? t("userPages.dialogue.connectionInterrupted")
            : apiError.name === 'AbortError'
            ? t("userPages.dialogue.aborted")
            : apiError.status === 401
              ? t("userPages.dialogue.authExpired")
              : apiError.status === 402
              ? (apiError.message || t("userPages.dialogue.creditExhausted"))
              : apiError.status === 403
              ? (apiError.message || t("userPages.dialogue.expertNotIncluded"))
              : apiError.status === 409
              ? (apiError.message || t("userPages.dialogue.planCreditRequired"))
              : apiError.message || t("userPages.dialogue.requestFailed");
        clearInitialTraceStatus(assistantIndex);
        if (answer) {
          updateAssistantMessage(assistantIndex, answer, latestSourceCount);
          setError(message);
        } else {
          updateAssistantMessage(assistantIndex, message, latestSourceCount, true);
        }
        const effectiveSessionId = sessionId || chat;
        if (effectiveSessionId && (isEof || isTimeout || (typeof apiError.status === 'number' && apiError.status >= 400))) {
          getChatSessionMessages(effectiveSessionId)
            .then((response) => {
              const msgs = getMessageList(response).flatMap(normalizeHistoryMessage);
              setExtraMessages(msgs);
            })
            .catch(() => { /* keep inline error on re-fetch failure */ });
        }
      }
    } finally {
      stopRequestedRef.current = false;
      currentTurnIdRef.current = '';
      setIsSending(false);
      streamAbortRef.current = null;
    }
  };

  const handleStop = () => {
    stopRequestedRef.current = true;
    const turnId = currentTurnIdRef.current;
    if (turnId) {
      // Call cancel API and keep the SSE stream open to receive turn_state.
      // Abort the stream as well so we fall through to the re-fetch path.
      cancelChatTurn(turnId).catch(() => {});
    }
    streamAbortRef.current?.abort();
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const text = prompt.trim();
    if ((!text && readyFileIds.length === 0) || isSending) return;

    await sendQuestion(text, { appendUserMessage: true, clearPrompt: true });
  };

  useEffect(() => {
    sendQuestionRef.current = sendQuestion;
  });

  // Auto-submit the first turn from sessionStorage when landing on a new dialogue.
  useEffect(() => {
    if (!pendingFirstTurn || chat || isSending) return;
    const { text, webSearchEnabled, attachments } = pendingFirstTurn;
    if (!text.trim() && attachments.length === 0) return;

    if (autoSubmittedPromptRef.current === text) return;
    autoSubmittedPromptRef.current = text;

    setActiveExpertTitle(expertName || (expert && expertTitleKeys[expert] ? t(expertTitleKeys[expert]) : '') || '');
    void sendQuestionRef.current?.(text, {
      appendUserMessage: true,
      clearPrompt: true,
      webSearchEnabled,
      attachmentFileIds: attachments,
    });
  }, [chat, expert, expertName, isSending, pendingFirstTurn, t]);

  return (
    <div className="dialogue-page flex h-full w-full flex-col">
      <div className="dialogue-body flex min-h-0 flex-1 flex-col">
        <section className="dialogue-messages messages" aria-live="polite" ref={messagesRef}>
          {chatMessages.map((message, index) => {
            if (message.role === 'user') {
              return (
                <article key={`${message.role}-${index}`} className="message user">
                  <div className="message-bubble user-bubble">
                    <MessageAttachmentList attachments={message.attachments} />
                    {message.text}
                  </div>
                </article>
              );
            }

            return (
              <article key={`${message.role}-${index}`} className="message assistant">
                <div className="message-bubble assistant-bubble">
                  <SourceBadge count={message.sourceCount} />
                  <AssistantTrace
                    items={message.traceItems}
                    autoOpen={isSending && index === chatMessages.length - 1}
                    isActive={isSending && index === chatMessages.length - 1}
                  />
                  <div className={`assistant-content${message.isError ? ' assistant-content-error' : ''}`}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{localizeStatus(message.markdown, t)}</ReactMarkdown>
                  </div>
                  {message.isFailed && (
                    <p className="ai-note text-[#b42318]" role="alert">
                      {message.errorText || t("userPages.dialogue.turnFailed")}
                    </p>
                  )}
                  {message.isStopped && (
                    <p className="ai-note text-[#606a78]">
                      {t("userPages.dialogue.stopped")}
                    </p>
                  )}
                  <SourcePill count={message.sourceCount} sources={message.sources} />
                  {message.turnAttachments?.filter((a) => a.source === 'personal_library_tool' && a.name).map((a, ai) => (
                    <div key={`${a.fileId ?? a.name}-${ai}`} className="mt-1 rounded-[8px] border border-[#e4ded7] bg-[#fafaf8] px-3 py-2 text-[12px] text-[#5c5650]">
                      <strong className="block text-[#25221f]">{a.name}</strong>
                      <span className="text-[#8a8580]">从个人资料读取
                        {a.readAt ? `· ${new Date(a.readAt).toLocaleString('zh-CN')}` : ''}
                      </span>
                    </div>
                  ))}
                  <AssistantActions
                    answerText={localizeStatus(message.markdown, t)}
                    onRetry={
                      index > 0 && chatMessages[index - 1]?.role === 'user'
                        ? () => {
                            const prevUser = chatMessages[index - 1];
                            if (prevUser.role !== 'user') return;
                            void retryQuestion(prevUser.text, index);
                          }
                        : undefined
                    }
                  />
                </div>
              </article>
            );
          })}
        </section>

        <div className="dialogue-footer">
          <form className={`composer ${activeExpertTitle ? 'expert-active' : ''}`} onSubmit={handleSubmit}>
            <label className="sr-only" htmlFor="promptInput">
              {t("userPages.dialogue.sendToWinWise")}
            </label>
            <ChatAttachmentChips attachments={attachments} onRemove={removeAttachment} />
            <textarea
              ref={textareaRef}
              id="promptInput"
              rows={1}
              value={prompt}
              onChange={(e) => {
                setPrompt(e.target.value);
                mention.onInput(e.target.value, e.target.selectionStart ?? e.target.value.length);
              }}
              onKeyDown={(event) => {
                if (mention.onKeyDown(event)) return;
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  if (!isSending) {
                    void handleSubmit(event as unknown as React.FormEvent<HTMLFormElement>);
                  }
                }
              }}
              placeholder={activeExpertTitle ? t("userPages.dialogue.askExpert", { title: activeExpertTitle }) : t("home.composerPlaceholder")}
              disabled={isSending}
            />
            {mention.popover}
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={(event) => handleAttachmentSelect(event.target.files)}
            />
            <div className="composer-footer">
              <div className="composer-left-icons">
                <button
                  className={`plain-tool relative group ${attachments.length > 0 ? 'active-tool' : ''}`}
                  type="button"
                  aria-label={t("home.uploadFile")}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <PaperclipIcon />
                  <span
                    className="pointer-events-none absolute bottom-[calc(100%+8px)] left-1/2 z-30 hidden -translate-x-1/2 whitespace-nowrap rounded-[8px] bg-[#111] px-2 py-1 text-[11px] leading-[1.2] text-white group-hover:block group-focus-visible:block"
                    aria-hidden="true"
                  >
                    {t("home.uploadFile")}
                  </span>
                </button>
                <button
                  className={`plain-tool relative group ${addFeatureState.webSearch ? 'active-tool' : ''}`}
                  type="button"
                  aria-label={t("home.webSearch")}
                  aria-pressed={addFeatureState.webSearch}
                  onClick={() => toggleAddFeature('webSearch')}
                >
                  <GlobeIcon />
                  <span
                    className="pointer-events-none absolute bottom-[calc(100%+8px)] left-1/2 z-30 hidden -translate-x-1/2 whitespace-nowrap rounded-[8px] bg-[#111] px-2 py-1 text-[11px] leading-[1.2] text-white group-hover:block group-focus-visible:block"
                    aria-hidden="true"
                  >
                    {t("home.webSearch")}
                  </span>
                </button>
                <div className="relative">
                  <button
                    ref={expertsTriggerRef}
                    type="button"
                    className={`inline-flex items-center gap-1 rounded-[8px] border border-[#e4dfd5] px-2 py-1 text-[12px] font-semibold text-[#232f3e] ${chat || isSending ? 'cursor-default bg-[#f5f0e8] opacity-70' : 'cursor-pointer bg-[#fbf6eb] hover:bg-[#f5edd4]'}`}
                    title={selectedExpertLabel}
                    aria-label={t("userPages.dialogue.currentExpert", { title: selectedExpertLabel })}
                    aria-expanded={chat || isSending ? undefined : isExpertsPopoverOpen}
                    disabled={!!(chat || isSending)}
                    onClick={() => { if (!chat && !isSending) setIsExpertsPopoverOpen((open) => !open); }}
                  >
                    <BookOpenIcon className="h-3.5 w-3.5" />
                    {selectedExpertLabel}
                  </button>
                  {isExpertsPopoverOpen && !chat && !isSending ? (
                    <div
                      ref={expertsPopoverRef}
                      className="composer-experts-popover"
                      style={{ bottom: 'calc(100% + 8px)', top: 'auto', left: 0 }}
                      aria-label={t("home.expertList")}
                    >
                      <p className="composer-experts-title">{t("home.experts")}</p>
                      <div className="composer-experts-filter">
                        <label>{t("home.expertCategory")}</label>
                        <Select
                          value={activeExpertCategory}
                          onChange={(value) => setActiveExpertCategory(value)}
                          disabled={isExpertsLoading}
                          style={{ width: '100%' }}
                          options={expertCategories.map((category) => ({ value: category.key, label: category.label }))}
                        />
                      </div>
                      <div className="composer-experts-list" aria-label={t("home.expertItems")}>
                        {filteredExpertCards.map((expertItem) => (
                          <button
                            key={expertItem.id}
                            type="button"
                            className={`composer-expert-item${!expertItem.isAccessible ? ' opacity-50' : ''}`}
                            aria-pressed={activeExpertId === expertItem.id}
                            disabled={!expertItem.isAccessible}
                            title={!expertItem.isAccessible ? t('home.expertNotAccessible') : undefined}
                            onClick={() => expertItem.isAccessible && selectExpert(expertItem)}
                          >
                            <span className="composer-expert-badge" aria-hidden="true">
                              {expertItem.short}
                            </span>
                            <span className="composer-expert-copy">
                              <strong>{expertItem.title}</strong>
                              <span>{expertItem.description}</span>
                            </span>
                          </button>
                        ))}
                        {isExpertsLoading ? (
                          <p className="composer-experts-empty">{t('home.expertsLoading')}</p>
                        ) : expertsError ? (
                          <p className="composer-experts-empty" role="alert">{expertsError}</p>
                        ) : filteredExpertCards.length === 0 ? (
                          <p className="composer-experts-empty">{t('home.emptyExperts')}</p>
                        ) : null}
                      </div>
                    </div>
                  ) : null}
                </div>
              </div>
              <div className="composer-right-icons">
                {isSending ? (
                  <button className="send-btn stop-btn" type="button" aria-label={t("userPages.dialogue.stopGeneration")} onClick={handleStop}>
                    <svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor" stroke="none">
                      <rect x="7" y="7" width="10" height="10" rx="1.5" />
                    </svg>
                  </button>
                ) : (
                  <button className="send-btn" type="submit" aria-label={t("userPages.common.send")} disabled={!prompt.trim() && readyFileIds.length === 0}>
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M12 19V5M5 12l7-7 7 7" />
                    </svg>
                  </button>
                )}
              </div>
            </div>
          </form>
          {error ? (
            <p className="ai-note text-[#b42318]" role="alert">
              {error}
            </p>
          ) : null}
          {pendingPermission ? (
            <div className="mx-auto mb-4 w-full max-w-[820px] rounded-[12px] border border-[#e4e7ee] bg-[#fffbf0] p-4">
              <p className="mb-3 text-[14px] font-semibold text-[#232f3e]">{t("userPages.dialogue.permissionRequired")}</p>
              <p className="mb-4 text-[13px] text-[#606a78]">{JSON.stringify(pendingPermission.data)}</p>
              <div className="flex gap-2">
                <button
                  type="button"
                  className="inline-flex h-8 items-center rounded-full bg-[#232f3e] px-4 text-[12px] font-semibold text-white"
                  onClick={() => {
                    const id = pendingPermission.permissionId;
                    setPendingPermission(null);
                    submitChatPermission(id, { outcome: 'cancelled' }).catch(() => {});
                  }}
                >
                  {t("userPages.dialogue.permissionCancel")}
                </button>
              </div>
            </div>
          ) : null}
        </div>

      </div>
    </div>
  );
}
