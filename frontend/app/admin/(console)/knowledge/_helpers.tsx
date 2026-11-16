import { Tag } from "antd";
import { type Translate } from "@/lib/i18n";
import {
  type KnowledgeBaseDocument,
  type KnowledgeBaseDocumentsResponse,
} from "@/lib/api/admin-client";

export const DOCUMENT_PAGE_SIZE = 50;

export type CreateFormValues = { name: string; description: string };
export type EditFormValues = { name: string; description: string };

export function knowledgeStatusTag(t: Translate, status = "") {
  if (status === "active") {
    return <Tag color="green">{t("adminKnowledge.statusActive")}</Tag>;
  }
  if (status === "archived") {
    return <Tag color="red">{t("adminKnowledge.statusArchived")}</Tag>;
  }
  return <Tag>{status || t("adminKnowledge.statusUnknown")}</Tag>;
}

export function formatDate(value?: string) {
  if (!value) return "-";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return `${date.getFullYear()}/${String(date.getMonth() + 1).padStart(2, "0")}/${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

export function formatFileSize(bytes?: number) {
  if (typeof bytes !== "number") return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;

  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function getErrorMessage(error: unknown, fallback: string) {
  if (error && typeof error === "object" && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }

  return fallback;
}

export function unwrapDocuments(response: KnowledgeBaseDocumentsResponse | undefined): KnowledgeBaseDocument[] {
  return response?.items ?? [];
}
