import { translate, type Locale } from "@/lib/i18n";
import { getChatSessions, type ChatSession } from "@/lib/api/chat";

export type HistoryItem = {
  id: string;
  title: string;
  isPinned: boolean;
};

export type HistoryGroup = {
  label: string;
  items: HistoryItem[];
};

export function readCookie(name: string) {
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`));

  return match ? decodeURIComponent(match.split("=")[1] ?? "") : "";
}

export function getSessionList(response: Awaited<ReturnType<typeof getChatSessions>> | undefined): ChatSession[] {
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

export function formatHistoryLabel(date: Date, locale: Locale) {
  const now = new Date();
  const dayDiff = Math.floor((now.getTime() - date.getTime()) / 86400000);
  if (dayDiff <= 0) return translate(locale, "appShell.today");
  if (dayDiff < 7) return translate(locale, "appShell.sevenDays");
  if (dayDiff < 30) return translate(locale, "appShell.thirtyDays");
  return date.toLocaleDateString(locale);
}

export function buildHistoryGroups(sessions: ChatSession[], locale: Locale): HistoryGroup[] {
  const groups = new Map<string, HistoryItem[]>();
  const sortedSessions = [...sessions].sort((a, b) => {
    const aTime = new Date(a.updatedAt || a.lastMessageAt || a.createdAt || 0).getTime();
    const bTime = new Date(b.updatedAt || b.lastMessageAt || b.createdAt || 0).getTime();

    return (Number.isNaN(bTime) ? 0 : bTime) - (Number.isNaN(aTime) ? 0 : aTime);
  });

  sortedSessions.forEach((session) => {
    const id = String(session.id ?? session.sessionId ?? session.chatId ?? "");
    if (!id) return;

    const title = session.title || session.name || session.summary || translate(locale, "appShell.unnamedChat");
    const dateValue = session.updatedAt || session.lastMessageAt || session.createdAt;
    const date = dateValue ? new Date(dateValue) : new Date();
    const label = session.isPinned ? translate(locale, "appShell.pinned") : Number.isNaN(date.getTime()) ? translate(locale, "appShell.thirtyDays") : formatHistoryLabel(date, locale);
    const items = groups.get(label) ?? [];

    items.push({ id, title, isPinned: Boolean(session.isPinned) });
    groups.set(label, items);
  });

  const preferredLabels = [
    translate(locale, "appShell.pinned"),
    translate(locale, "appShell.today"),
    translate(locale, "appShell.sevenDays"),
    translate(locale, "appShell.thirtyDays"),
  ];
  const orderedGroups: HistoryGroup[] = [];

  preferredLabels.forEach((label) => {
    const items = groups.get(label);
    if (items?.length) orderedGroups.push({ label, items });
    groups.delete(label);
  });

  return [
    ...orderedGroups,
    ...Array.from(groups, ([label, items]) => ({ label, items })),
  ];
}

export function getSessionId(session: ChatSession) {
  return String(session.id ?? session.sessionId ?? session.chatId ?? "");
}
