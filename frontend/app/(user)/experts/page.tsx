"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import {
  getExpertMarketCategories,
  getExpertMarketExperts,
  type ExpertMarketCategory,
  type ExpertMarketExpert,
} from "@/lib/api/expert-market";

type ExpertView = {
  id: string;
  title: string;
  categoryId: string;
  categoryName: string;
  intro: string;
  iconPath: string;
  iconTone: string;
  tags: string[];
  prompts: string[];
  summonButtonText: string;
  knowledgeBaseCount: number;
  hot: boolean;
  isAccessible: boolean;
};

const allCategoryId = "all";

const cjkTextPattern = /[\u3400-\u9fff]/;

function hasCjkText(value: string | null | undefined) {
  return Boolean(value && cjkTextPattern.test(value));
}

function localizedText(
  locale: string,
  localizedValue: string | null | undefined,
  fallbackValue: string | null | undefined,
  englishFallback: string,
) {
  const localized = localizedValue?.trim();
  if (localized && (locale === "zh-CN" || !hasCjkText(localized))) return localized;

  const fallback = fallbackValue?.trim();
  if (fallback && (locale === "zh-CN" || !hasCjkText(fallback))) return fallback;

  return englishFallback;
}

function localizedList(locale: string, values: string[] | undefined) {
  const normalized = (values ?? []).map((value) => value.trim()).filter(Boolean);
  return locale === "zh-CN" ? normalized : normalized.filter((value) => !hasCjkText(value));
}

function localizedActionText(
  locale: string,
  localizedValue: string | null | undefined,
  fallbackValue: string | null | undefined,
  englishFallback: string,
  expertTitle: string,
) {
  const localized = localizedValue?.trim();
  if (localized && (locale === "zh-CN" || !hasCjkText(localized))) return localized;

  const normalized = fallbackValue?.trim();
  if (!normalized || locale === "zh-CN" || !hasCjkText(normalized)) return normalized || englishFallback;

  const summonMatch = normalized.match(/^召唤\s*(.*)$/);
  if (summonMatch) {
    const suffix = summonMatch[1].trim();
    if (!suffix) return `Summon ${expertTitle}`;
    if (suffix === "专家") return "Summon expert";
    if (!hasCjkText(suffix)) return `Summon ${suffix}`;
    return `Summon ${expertTitle}`;
  }

  return englishFallback;
}

const iconPresets = [
  { tone: "bg-[#e8f3ff] text-[#25508b]", path: "M4 20V9l8-5 8 5v11M8 20v-7h8v7" },
  { tone: "bg-[#edf7e5] text-[#4e7d24]", path: "M5 20V9h4v11M10 20V4h4v16M15 20v-8h4v8" },
  { tone: "bg-[#fff1d5] text-[#9a5f00]", path: "M4 13h4l9-6v10l-9-4H4Zm4 0v5" },
  { tone: "bg-[#f0eee8] text-[#33302c]", path: "M5 19h14M7 17 17.5 6.5l-3-3L4 14v3h3Z" },
  { tone: "bg-[#fff0ec] text-[#9f3b21]", path: "M12 3 5 6v6c0 4.5 3 7.5 7 9 4-1.5 7-4.5 7-9V6l-7-3Z" },
  { tone: "bg-[#e8f8f2] text-[#27775b]", path: "M4 18h16M6 15l4-4 3 3 5-7" },
];

function getPreset(index: number) {
  return iconPresets[index % iconPresets.length];
}

function getExpertList(response: Awaited<ReturnType<typeof getExpertMarketExperts>> | undefined) {
  return Array.isArray(response?.items) ? response.items : [];
}

function getCategoryList(response: Awaited<ReturnType<typeof getExpertMarketCategories>> | undefined) {
  return Array.isArray(response?.items) ? response.items : [];
}

function ExpertIcon({ expert, className = "h-12 w-12" }: { expert: ExpertView; className?: string }) {
  return (
    <span className={`grid ${className} shrink-0 place-items-center rounded-[16px] ${expert.iconTone}`}>
      <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d={expert.iconPath} />
      </svg>
    </span>
  );
}

export default function ExpertsPage() {
  const { t, locale } = useI18n();
  const toast = useToast();
  const [activeCategoryId, setActiveCategoryId] = useState(allCategoryId);
  const [activeExpert, setActiveExpert] = useState<ExpertView | null>(null);
  const [experts, setExperts] = useState<ExpertView[]>([]);
  const [categories, setCategories] = useState<ExpertMarketCategory[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const toExpertView = useCallback((expert: ExpertMarketExpert, index: number): ExpertView => {
    const preset = getPreset(index);
    const content = expert.localizedContent?.[locale === "zh-CN" ? "zh" : "en"];
    const categoryName = localizedText(
      locale,
      content?.categoryName,
      expert.categoryName,
      t("userPages.experts.uncategorized"),
    );
    const title = localizedText(locale, content?.name, expert.name, t("userPages.experts.defaultTag"));
    const tags = localizedList(locale, expert.tags);
    const prompts = localizedList(locale, expert.guideQuestions);

    return {
      id: expert.id,
      title,
      categoryId: expert.categoryId || "uncategorized",
      categoryName,
      intro: localizedText(locale, content?.abilityIntro, expert.abilityIntro, t("userPages.experts.noIntro")),
      iconPath: preset.path,
      iconTone: preset.tone,
      tags: tags.length ? tags : [categoryName || t("userPages.experts.defaultTag")],
      prompts,
      summonButtonText: localizedActionText(
        locale,
        content?.summonButtonText,
        expert.summonButtonText,
        t("userPages.experts.summon"),
        title,
      ),
      knowledgeBaseCount: expert.knowledgeBaseIds?.length ?? 0,
      hot: (expert.marketLabels ?? []).includes("hot"),
      isAccessible: expert.isAccessible,
    };
  }, [locale, t]);

  function dialogueHref(expert: ExpertView, prompt?: string) {
    const params = new URLSearchParams({
      expert: expert.id,
      expertName: expert.title,
      prompt: prompt || expert.prompts[0] || t("userPages.experts.defaultPrompt", { title: expert.title }),
    });

    return `/dialogue?${params.toString()}`;
  }

  const categoryOptions = useMemo(() => {
    const options = new Map<string, string>();

    categories.forEach((category) => {
      if (category.id && category.name && (locale === "zh-CN" || !hasCjkText(category.name))) {
        options.set(category.id, category.name);
      }
    });

    experts.forEach((expert) => {
      if (expert.categoryId) options.set(expert.categoryId, expert.categoryName);
    });

    return [{ id: allCategoryId, name: t("userPages.experts.all") }, ...Array.from(options, ([id, name]) => ({ id, name }))];
  }, [categories, experts, locale, t]);

  const filteredExperts = useMemo(() => {
    if (activeCategoryId === allCategoryId) return experts;
    return experts.filter((expert) => expert.categoryId === activeCategoryId);
  }, [activeCategoryId, experts]);

  useEffect(() => {
    let ignore = false;

    Promise.allSettled([getExpertMarketExperts(), getExpertMarketCategories()])
      .then(([expertsResult, categoriesResult]) => {
        if (ignore) return;

        if (expertsResult.status === "fulfilled") {
          setExperts(getExpertList(expertsResult.value).map((expert, index) => toExpertView(expert, index)));
        } else {
          setExperts([]);
          toast.error(t("userPages.experts.loadFailed"));
        }

        setCategories(categoriesResult.status === "fulfilled" ? getCategoryList(categoriesResult.value) : []);
      })
      .finally(() => {
        if (!ignore) setIsLoading(false);
      });

    return () => {
      ignore = true;
    };
  }, [t, toExpertView]);

  useEffect(() => {
    if (!categoryOptions.some((category) => category.id === activeCategoryId)) {
      queueMicrotask(() => setActiveCategoryId(allCategoryId));
    }
  }, [activeCategoryId, categoryOptions]);

  return (
    <div className="mx-auto flex h-full w-full max-w-[1120px] flex-col overflow-hidden">
      <header className="flex flex-col gap-5 pb-6 pt-2">
        <div>
          <p className="mb-2 text-[13px] font-semibold uppercase tracking-[0.18em] text-[#f39c12]">{t("userPages.experts.eyebrow")}</p>
          <h1 className="text-[28px] font-bold text-[#1d232c]">{t("userPages.experts.title")}</h1>
          <p className="mt-2 max-w-[640px] text-[14px] leading-[1.7] text-[#707783]">{t("userPages.experts.description")}</p>
        </div>
      </header>

      <div className="mb-6 flex gap-2 overflow-x-auto pb-1" aria-label={t("userPages.experts.categoryLabel")}>
        {categoryOptions.map((category) => (
          <button
            key={category.id}
            type="button"
            onClick={() => setActiveCategoryId(category.id)}
            className={`h-9 shrink-0 rounded-full border px-4 text-[13px] transition ${
              activeCategoryId === category.id
                ? "border-[#232f3e] bg-[#232f3e] text-white"
                : "border-[#e4e7ee] bg-white text-[#4b5563] hover:border-[#f39c12] hover:text-[#232f3e]"
            }`}
          >
            {category.name}
          </button>
        ))}
      </div>

      <section className="min-h-0 flex-1 overflow-y-auto pb-8" aria-label={t("userPages.experts.listLabel")}>
        {isLoading ? (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="rounded-[24px] border border-[#ece8e2] bg-white p-5">
                <div className="flex items-start gap-4">
                  <div className="h-12 w-12 rounded-[16px] bg-[#f1f3f6]" />
                  <div className="flex-1 space-y-3">
                    <div className="h-5 w-40 rounded-full bg-[#f1f3f6]" />
                    <div className="h-4 w-64 max-w-full rounded-full bg-[#f6f7f9]" />
                  </div>
                </div>
                <div className="mt-5 h-16 rounded-[14px] bg-[#f6f7f9]" />
              </div>
            ))}
          </div>
        ) : null}

        {!isLoading && !filteredExperts.length ? (
          <div className="rounded-[18px] border border-[#ece8e2] bg-white px-5 py-8 text-center text-[14px] text-[#707783]">{t("userPages.experts.empty")}</div>
        ) : null}

        {!isLoading && filteredExperts.length ? (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {filteredExperts.map((expert) => (
              <article key={expert.id} className="group rounded-[24px] border border-[#ece8e2] bg-white p-5 shadow-[0_1px_0_rgba(20,26,36,0.02)] transition hover:-translate-y-0.5 hover:border-[#f1dec1] hover:shadow-[0_18px_45px_rgba(35,47,62,0.08)]">
                <div className="flex items-start gap-4">
                  <ExpertIcon expert={expert} />
                  <div className="min-w-0 flex-1">
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <h2 className="text-[17px] font-bold text-[#242a34]">{expert.title}</h2>
                      {expert.hot ? <span className="rounded-full bg-[#fff4e2] px-2 py-0.5 text-[11px] font-semibold text-[#9a5f00]">{t("userPages.experts.hot")}</span> : null}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {expert.tags.map((tag) => (
                        <span key={tag} className="rounded-full bg-[#f6f7f9] px-2.5 py-1 text-[12px] text-[#596273]">{tag}</span>
                      ))}
                    </div>
                  </div>
                </div>

                <p className="mt-4 text-[14px] leading-[1.8] text-[#606a78]">{expert.intro}</p>

                <div className="mt-5 flex flex-wrap items-center gap-3">
                  <button type="button" onClick={() => setActiveExpert(expert)} className="inline-flex h-10 items-center justify-center rounded-full border border-[#e4e7ee] bg-white px-4 text-[13px] font-semibold text-[#252b35] hover:border-[#f39c12] hover:text-[#232f3e]">
                    {t("userPages.experts.details")}
                  </button>
                  {expert.isAccessible ? (
                    <Link href={dialogueHref(expert)} className="inline-flex h-10 items-center justify-center rounded-full bg-[#f39c12] px-4 text-[13px] font-semibold text-white shadow-[0_10px_20px_rgba(243,156,18,0.22)]">
                      {expert.summonButtonText} -&gt;
                    </Link>
                  ) : (
                    <span className="inline-flex h-10 items-center justify-center rounded-full bg-[#e4e7ee] px-4 text-[13px] font-semibold text-[#9ca3af]" title={t("userPages.experts.notAccessible")}>
                      {expert.summonButtonText}
                    </span>
                  )}
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </section>

      {activeExpert ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-[rgba(20,24,32,0.34)] px-4" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setActiveExpert(null);
        }}>
          <section role="dialog" aria-modal="true" aria-labelledby="expert-dialog-title" className="max-h-[86vh] w-full max-w-[620px] overflow-y-auto rounded-[28px] border border-[#ece8e2] bg-white p-6 shadow-[0_30px_90px_rgba(20,24,32,0.22)]">
            <div className="flex items-start gap-4">
              <ExpertIcon expert={activeExpert} className="h-14 w-14" />
              <div className="min-w-0 flex-1">
                <p className="mb-1 text-[13px] font-semibold text-[#f39c12]">{activeExpert.categoryName}</p>
                <h2 id="expert-dialog-title" className="text-[22px] font-bold text-[#1d232c]">{activeExpert.title}</h2>
              </div>
              <button type="button" onClick={() => setActiveExpert(null)} className="grid h-9 w-9 place-items-center rounded-full border border-[#e4e7ee] text-[#6b7280] hover:bg-[#f6f7f9]" aria-label={t("userPages.common.close")}>
                x
              </button>
            </div>

            <p className="mt-5 text-[14px] leading-[1.8] text-[#4b5563]">{activeExpert.intro}</p>

            <h3 className="mt-6 text-[14px] font-bold text-[#242a34]">{t("userPages.experts.abilityTags")}</h3>
            <div className="mt-3 flex flex-wrap gap-2">
              {activeExpert.tags.map((tag) => <span key={tag} className="rounded-full bg-[#f7f5f2] px-3 py-1.5 text-[12px] text-[#5f6673]">{tag}</span>)}
              {activeExpert.knowledgeBaseCount ? (
                <span className="rounded-full bg-[#f7f5f2] px-3 py-1.5 text-[12px] text-[#5f6673]">{t("userPages.experts.kbCount", { count: activeExpert.knowledgeBaseCount })}</span>
              ) : null}
            </div>

            <h3 className="mt-6 text-[14px] font-bold text-[#242a34]">{t("userPages.experts.promptsTitle")}</h3>
            {activeExpert.prompts.length ? (
              <div className="mt-3 grid gap-2">
                {activeExpert.prompts.map((prompt) => (
                  activeExpert.isAccessible ? (
                    <Link key={prompt} href={dialogueHref(activeExpert, prompt)} className="flex items-center justify-between gap-4 rounded-[14px] border border-[#ece8e2] bg-[#fbfaf8] px-4 py-3 text-left text-[13px] leading-[1.6] text-[#374151] hover:border-[#f39c12] hover:bg-[#fffaf1]">
                      <span>{prompt}</span>
                      <span className="text-[18px] text-[#f39c12]">-&gt;</span>
                    </Link>
                  ) : (
                    <div key={prompt} className="flex items-center justify-between gap-4 rounded-[14px] border border-[#ece8e2] bg-[#fbfaf8] px-4 py-3 text-left text-[13px] leading-[1.6] text-[#9ca3af] opacity-60">
                      <span>{prompt}</span>
                    </div>
                  )
                ))}
              </div>
            ) : (
              <p className="mt-3 rounded-[14px] border border-[#ece8e2] bg-[#fbfaf8] px-4 py-3 text-[13px] text-[#707783]">{t("userPages.experts.noPrompts")}</p>
            )}

            <div className="mt-6 flex justify-end">
              {activeExpert.isAccessible ? (
                <Link href={dialogueHref(activeExpert)} className="inline-flex h-11 items-center justify-center rounded-full bg-[#232f3e] px-5 text-[14px] font-semibold text-white">
                  {activeExpert.summonButtonText}
                </Link>
              ) : (
                <span className="inline-flex h-11 items-center justify-center rounded-full bg-[#e4e7ee] px-5 text-[14px] font-semibold text-[#9ca3af]" title={t("userPages.experts.notAccessible")}>
                  {activeExpert.summonButtonText}
                </span>
              )}
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
