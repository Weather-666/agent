'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Select } from 'antd';
import { useI18n } from '@/lib/i18n';
import { useRouter } from 'next/navigation';
import {
  getExpertMarketCategories,
  getExpertMarketExperts,
  type ExpertMarketCategory,
  type ExpertMarketExpert,
} from '@/lib/api/expert-market';
import {
  getFeaturedMarketExamples,
  useFeaturedMarketExample,
  type FeaturedMarketItem,
} from '@/lib/api/featured';
import { ChatAttachmentChips, useChatAttachments } from '@/lib/chat-attachments';
import {
  DEFAULT_EXPERT_SELECTION_ID,
  createDefaultExpertCard,
  type ExpertSelectionCard,
} from '@/lib/default-expert';
import { useLibraryMention } from '@/lib/library-mention';

const allCategoryId = 'all';

type ExpertCategoryOption = {
  key: string;
  label: string;
};

type AddFeatureKey = 'webSearch';

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
  const starter = expert.guideQuestions?.find((question) => typeof question === 'string' && question.trim()) || '';

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

export default function HomePage() {
  const { t, locale } = useI18n();
  const router = useRouter();
  const [prompt, setPrompt] = useState('');
  const [isExpertsPopoverOpen, setIsExpertsPopoverOpen] = useState(false);
  const [selectedExpertId, setSelectedExpertId] = useState(DEFAULT_EXPERT_SELECTION_ID);
  const [activeExpertCategory, setActiveExpertCategory] = useState(allCategoryId);
  const [marketExpertCards, setMarketExpertCards] = useState<ExpertSelectionCard[]>([]);
  const [marketCategories, setMarketCategories] = useState<ExpertMarketCategory[]>([]);
  const [isExpertsLoading, setIsExpertsLoading] = useState(true);
  const [expertsError, setExpertsError] = useState('');
  const [addFeatureState, setAddFeatureState] = useState<Record<AddFeatureKey, boolean>>({
    webSearch: false,
  });
  const [attachmentError, setAttachmentError] = useState('');
  const [featuredExamples, setFeaturedExamples] = useState<FeaturedMarketItem[]>([]);
  const [featuredLoading, setFeaturedLoading] = useState(true);
  const [featuredError, setFeaturedError] = useState('');
  const [usingExampleId, setUsingExampleId] = useState('');
  const { attachments, addFiles, addLibraryFile, removeAttachment, readyFileIds } = useChatAttachments((kind) =>
    setAttachmentError(
      kind === 'auth'
        ? t("userPages.dialogue.authExpired")
        : kind === 'tooLarge'
        ? t("userPages.dialogue.attachmentTooLarge")
        : t("userPages.dialogue.attachmentUploadFailed"),
    ),
  );
  const [expertsPopoverPosition, setExpertsPopoverPosition] = useState({ left: 12, top: 0, maxHeight: 520 });
  const formRef = useRef<HTMLFormElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const expertsTriggerRef = useRef<HTMLButtonElement | null>(null);
  const expertsPopoverRef = useRef<HTMLDivElement | null>(null);
  const mention = useLibraryMention({
    value: prompt,
    onChange: setPrompt,
    textareaRef,
    onSelect: addLibraryFile,
    excludeIds: readyFileIds,
  });

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
  const selectedExpert = useMemo(
    () => expertCards.find((card) => card.id === selectedExpertId) ?? defaultExpertCard,
    [defaultExpertCard, expertCards, selectedExpertId],
  );

  const filteredExpertCards = useMemo(() => {
    if (activeExpertCategory === allCategoryId) return expertCards;
    return expertCards.filter((item) => item.categoryId === activeExpertCategory);
  }, [activeExpertCategory, expertCards]);

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

  useEffect(() => {
    if (expertCategories.some((category) => category.key === activeExpertCategory)) return;
    queueMicrotask(() => setActiveExpertCategory(allCategoryId));
  }, [activeExpertCategory, expertCategories]);

  // A removed/unpublished market expert falls back to the product-level default route.
  useEffect(() => {
    if (expertCards.some((item) => item.id === selectedExpertId)) return;
    queueMicrotask(() => setSelectedExpertId(DEFAULT_EXPERT_SELECTION_ID));
  }, [expertCards, selectedExpertId]);

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

  useEffect(() => {
    if (!isExpertsPopoverOpen) return;

    function updateExpertsPopoverPosition() {
      const formElement = formRef.current;
      const triggerElement = expertsTriggerRef.current;
      if (!formElement || !triggerElement) return;

      const formRect = formElement.getBoundingClientRect();
      const triggerRect = triggerElement.getBoundingClientRect();
      const popoverWidth = expertsPopoverRef.current?.offsetWidth ?? 360;
      const preferredLeft = triggerRect.right - formRect.left + 8;
      const maxLeft = Math.max(8, formRect.width - popoverWidth - 8);

      const spaceBelow = window.innerHeight - triggerRect.bottom - 16;
      setExpertsPopoverPosition({
        left: Math.min(preferredLeft, maxLeft),
        top: triggerRect.bottom - formRect.top + 8,
        maxHeight: Math.max(180, Math.min(spaceBelow, 520)),
      });
    }

    updateExpertsPopoverPosition();
    window.addEventListener('resize', updateExpertsPopoverPosition);

    return () => {
      window.removeEventListener('resize', updateExpertsPopoverPosition);
    };
  }, [isExpertsPopoverOpen]);

  useEffect(() => {
    let ignore = false;
    setFeaturedLoading(true);
    getFeaturedMarketExamples()
      .then((data) => {
        if (ignore) return;
        setFeaturedExamples(Array.isArray(data?.items) ? data.items : []);
        setFeaturedError('');
      })
      .catch((err: { message?: string }) => {
        if (ignore) return;
        setFeaturedError(err?.message ?? t('home.featuredLoadFailed'));
      })
      .finally(() => {
        if (!ignore) setFeaturedLoading(false);
      });
    return () => { ignore = true; };
  }, [t]);

  async function handleExampleClick(example: FeaturedMarketItem) {
    if (usingExampleId) return;
    setUsingExampleId(example.id);
    try {
      const result = await useFeaturedMarketExample(example.id);
      startDialogue(result.question);
    } catch (err: unknown) {
      const e = err as { message?: string; code?: string; status?: number };
      const status = e?.status;
      const code = e?.code;
      if (status === 404 || code === 'FEATURED_EXAMPLE_NOT_FOUND') {
        setFeaturedError(t('home.featuredExampleUnavailable'));
        // Refresh list
        getFeaturedMarketExamples()
          .then((data) => setFeaturedExamples(Array.isArray(data?.items) ? data.items : []))
          .catch(() => {});
      } else if (status === 409 || code === 'FEATURED_EXAMPLE_UNAVAILABLE') {
        setFeaturedError(t('home.featuredExampleUnavailable'));
        getFeaturedMarketExamples()
          .then((data) => setFeaturedExamples(Array.isArray(data?.items) ? data.items : []))
          .catch(() => {});
      } else {
        setFeaturedError(e?.message ?? t('home.featuredLoadFailed'));
      }
    } finally {
      setUsingExampleId('');
    }
  }

  function startDialogue(text: string) {
    const question = text.trim();
    const expert = selectedExpert;

    // Write first-turn data to sessionStorage so the full prompt never enters the URL.
    // This avoids 431 errors for long inputs and prevents re-submission on refresh.
    try {
      sessionStorage.setItem('winwise.pending-first-turn.v1', JSON.stringify({
        text: question || expert.starter || '',
        webSearchEnabled: addFeatureState.webSearch,
        attachments: readyFileIds,
      }));
    } catch { /* ignore quota errors — dialogue page handles missing data gracefully */ }
    const params = new URLSearchParams({ expert: expert.id, expertName: expert.title });
    router.push(`/dialogue?${params.toString()}`);
  }

  function handleAttachmentSelect(fileList: FileList | null) {
    setAttachmentError('');
    addFiles(fileList);
    // Reset so selecting the same file again re-triggers onChange.
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    startDialogue(prompt);
  }

  function selectExpert(expert: ExpertSelectionCard) {
    setSelectedExpertId(expert.id);
    setIsExpertsPopoverOpen(false);
  }

  function toggleAddFeature(feature: AddFeatureKey) {
    setAddFeatureState((current) => ({ ...current, [feature]: !current[feature] }));
  }

  return (
    <div className="mx-auto w-full max-w-[980px]">
      <header className="mb-14 mt-10 text-center">
        <div className="inline-flex items-center gap-3">
          <span className="grid h-[34px] w-[34px] place-items-center rounded-full bg-[#232f3e] text-[17px] font-extrabold text-white">W</span>
          <h2 className="text-[30px] font-bold text-[#1f1b1d]">WinWise</h2>
        </div>
        <p className="mt-3 text-[16px] text-[#a4a9b3]">{t("home.composerPlaceholder")}</p>
      </header>

      <form ref={formRef} className="composer mx-auto mb-4" onSubmit={handleSubmit}>
        <ChatAttachmentChips attachments={attachments} onRemove={removeAttachment} />
        <div className="px-[18px] pt-5">
          <label className="sr-only" htmlFor="homePrompt">{t("home.composerPlaceholder")}</label>
          <textarea
            ref={textareaRef}
            id="homePrompt"
            rows={1}
            value={prompt}
            onChange={(event) => {
              setPrompt(event.target.value);
              mention.onInput(event.target.value, event.target.selectionStart ?? event.target.value.length);
            }}
            onKeyDown={(event) => {
              if (mention.onKeyDown(event)) return;
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                startDialogue(prompt);
              }
            }}
            className="min-h-[44px] w-full resize-none border-0 border-b border-[#ececec] bg-transparent pb-4 text-[16px] leading-7 text-[#1f1b1d] outline-none placeholder:text-[#b0b5bf]"
            placeholder={t("home.composerPlaceholder")}
          />
          {mention.popover}
        </div>
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
            {selectedExpert ? (
              <button
                ref={expertsTriggerRef}
                type="button"
                className="selected-expert-chip"
                title={selectedExpert.title}
                aria-label={t("home.selectedExpert", { title: selectedExpert.title })}
                aria-expanded={isExpertsPopoverOpen}
                aria-controls="home-experts-popover"
                onClick={() => setIsExpertsPopoverOpen((open) => !open)}
              >
                <BookOpenIcon className="h-[15px] w-[15px]" />
                <span className="selected-expert-chip-name">{selectedExpert.title}</span>
              </button>
            ) : (
              <button
                ref={expertsTriggerRef}
                className="plain-tool relative group"
                type="button"
                aria-label={t("home.experts")}
                aria-expanded={isExpertsPopoverOpen}
                aria-controls="home-experts-popover"
                onClick={() => {
                  setIsExpertsPopoverOpen((open) => !open);
                }}
              >
                <BookOpenIcon />
                <span
                  className="pointer-events-none absolute bottom-[calc(100%+8px)] left-1/2 z-30 hidden -translate-x-1/2 whitespace-nowrap rounded-[8px] bg-[#111] px-2 py-1 text-[11px] leading-[1.2] text-white group-hover:block group-focus-visible:block"
                  aria-hidden="true"
                >
                  {t("home.experts")}
                </span>
              </button>
            )}
          </div>

          <div className="composer-right-icons">
            <button
              className="send-btn"
              type="submit"
              disabled={!prompt.trim() && readyFileIds.length === 0 && !selectedExpert}
              aria-label={t("home.send")}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 19V5M5 12l7-7 7 7" />
              </svg>
            </button>
          </div>
        </div>
        {isExpertsPopoverOpen ? (
          <div
            ref={expertsPopoverRef}
            id="home-experts-popover"
            className="composer-experts-popover"
            aria-label={t("home.expertList")}
            style={{
              left: `${expertsPopoverPosition.left}px`,
              top: `${expertsPopoverPosition.top}px`,
              maxHeight: `${expertsPopoverPosition.maxHeight}px`,
            }}
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
              {filteredExpertCards.map((expert) => (
                <button
                  key={expert.id}
                  type="button"
                  className={`composer-expert-item${!expert.isAccessible ? ' opacity-50' : ''}`}
                  aria-pressed={selectedExpert?.id === expert.id}
                  disabled={!expert.isAccessible}
                  title={!expert.isAccessible ? t("home.expertNotAccessible") : undefined}
                  onClick={() => expert.isAccessible && selectExpert(expert)}
                >
                  <span className="composer-expert-badge" aria-hidden="true">
                    {expert.short}
                  </span>
                  <span className="composer-expert-copy">
                    <strong>{expert.title}</strong>
                    <span>{expert.description}</span>
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
      </form>

      {attachmentError ? (
        <p className="mx-auto mb-4 max-w-[980px] text-[13px] text-[#b42318]" role="alert">
          {attachmentError}
        </p>
      ) : null}

      {(featuredLoading || featuredExamples.length > 0 || featuredError) ? (
        <section className="mx-auto w-full max-w-[980px]">
          <div className="mb-[14px] flex items-center justify-between">
            <h3 className="text-[15px] font-extrabold text-[#1f1b1d]">{t("home.featuredExamples")}</h3>
          </div>

          {featuredError ? (
            <p className="mb-4 text-[13px] text-[#b42318]" role="alert">{featuredError}</p>
          ) : null}

          {featuredLoading ? (
            <div className="grid grid-cols-1 gap-[14px] md:grid-cols-2 xl:grid-cols-4">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="h-[78px] animate-pulse rounded-[10px] bg-[#f1f3f6]" />
              ))}
            </div>
          ) : featuredExamples.length > 0 ? (
            <div className="grid grid-cols-1 gap-[14px] md:grid-cols-2 xl:grid-cols-4">
              {featuredExamples.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  disabled={Boolean(usingExampleId)}
                  className="rounded-[10px] border border-[#eee7dd] bg-white text-left shadow-[0_6px_18px_rgba(31,27,29,0.05)] hover:border-[#ffcb7d] hover:shadow-[0_10px_24px_rgba(31,27,29,0.08)] disabled:opacity-60"
                  onClick={() => handleExampleClick(item)}
                >
                  <h4 className="px-3 pb-[7px] pt-[14px] text-[14px] font-medium leading-[1.5] text-[#1f1b1d]">
                    {item.question}
                  </h4>
                  <p className="px-3 pb-3 text-[12px] text-[#9b938b]">
                    {item.categoryName} · {item.clickCount.toLocaleString()}
                  </p>
                </button>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
