import { type ExpertStatus } from "@/lib/api/admin-client";
import { type KnowledgeBase } from "@/lib/api/admin-client";
import { type Skill } from "@/lib/api/admin-client";

export const STATUS_VALUES: ExpertStatus[] = ["published", "draft", "unlisted"];

export const statusTagColor: Record<ExpertStatus, string> = {
  published: "green",
  draft: "gold",
  unlisted: "default",
};

export type ExpertFormValues = {
  zhName: string;
  enName: string;
  zhIntro: string;
  enIntro: string;
  zhCategoryName: string;
  enCategoryName: string;
  categoryId: string;
  instructions: string;
  tags: string;
  skillIds: string[];
  knowledgeBaseId: string;
  guideQuestions: string[];
  zhCtaText: string;
  enCtaText: string;
  hot: boolean;
  mcpConnectorIds: string[];
};

export function normalizeList(value: string) {
  return value
    .split(/[,\n，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function getErrorMessage(error: unknown, fallback: string) {
  if (error && typeof error === "object" && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }

  return fallback;
}

export function getKbLabel(knowledgeBase: KnowledgeBase) {
  return knowledgeBase.name || knowledgeBase.id;
}

export function getSkillLabel(skill: Skill) {
  return skill.name || skill.slug;
}

export function getSkillId(skill: Skill) {
  return skill.id || skill.slug;
}

export function emptyFormValues(): ExpertFormValues {
  return {
    zhName: "",
    enName: "",
    zhIntro: "",
    enIntro: "",
    zhCategoryName: "",
    enCategoryName: "",
    categoryId: "",
    instructions: "",
    tags: "",
    skillIds: [],
    knowledgeBaseId: "",
    guideQuestions: ["", "", ""],
    zhCtaText: "",
    enCtaText: "",
    hot: false,
    mcpConnectorIds: [],
  };
}
