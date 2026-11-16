import { type MessageKey } from "@/lib/i18n";
import {
  createChatSession,
  getChatSessionMessages,
  type ChatSession,
  type ChatSessionMessage,
} from "@/lib/api/chat";
import { type MessageAttachment } from "@/lib/chat-attachments";

export type { MessageAttachment };

export type AssistantTraceItem = {
  kind: 'thinking' | 'action';
  text: string;
  id?: string;
};

export type AddFeatureKey = 'webSearch';

export type CitationSource = {
  citationId: string | null;
  citationIds: string[];
  knowledgeBaseId: string | null;
  knowledgeBaseName: string | null;
  documentId: string | null;
  fileName: string;
  pageNumber: number | null;
  mimeType: string | null;
  hitText: string | null;
  locator: Record<string, unknown>;
  previewUrl: string | null;
  downloadUrl: string | null;
  available: boolean;
};

// Full turn state from turn_snapshot / turn_state events.
export type TurnSnapshotData = {
  id?: string;
  turnId?: string;
  sessionId?: string;
  responseText?: string | null;
  reasoningText?: string | null;
  status?: string;
  stopReason?: string | null;
  errorMessage?: string | null;
  attachments?: import('@/lib/api/chat').ChatTurnAttachment[];
  retrievalRefs?: unknown[];
  eventSeq?: number;
};

export type ChatMessage =
  | {
      role: 'user';
      text: string;
      attachments?: MessageAttachment[];
    }
  | {
      role: 'assistant';
      turnId?: string;
      eventSeq?: number;
      isStreaming?: boolean;
      markdown: string;
      sourceCount: number;
      sources?: CitationSource[];
      traceItems: AssistantTraceItem[];
      isError?: boolean;
      isStopped?: boolean;
      isFailed?: boolean;
      errorText?: string;
      turnAttachments?: import('@/lib/api/chat').ChatTurnAttachment[];
    };

export const expertTitleKeys: Record<string, MessageKey> = {
  store: 'userPages.dialogue.expertStore',
  product: 'userPages.dialogue.expertProduct',
  ads: 'userPages.dialogue.expertAds',
  listing: 'userPages.dialogue.expertListing',
  compliance: 'userPages.dialogue.expertCompliance',
  data: 'userPages.dialogue.expertData',
};

// Status/placeholder strings are produced as canonical zh-CN sentinels deep in the
// stream-parsing layer (and compared there for dedup/placeholder filtering). We keep
// those sentinels stable and only localize them at the render boundary via this map.
export const statusKeyByText: Record<string, MessageKey> = {
  '正在思考...': 'userPages.dialogue.thinking',
  '正在连接智能体，准备分析问题': 'userPages.dialogue.connecting',
  '正在整理回答...': 'userPages.dialogue.organizing',
  '正在组织最终回答。': 'userPages.dialogue.finalizing',
  '已停止': 'userPages.dialogue.stopped',
  '正在检索知识库': 'userPages.dialogue.kbSearching',
  '已完成知识库检索': 'userPages.dialogue.kbDone',
  '正在执行工具': 'userPages.dialogue.toolRunning',
  '已完成工具执行': 'userPages.dialogue.toolDone',
  '正在处理资料': 'userPages.dialogue.dataProcessing',
  '已完成资料处理': 'userPages.dialogue.dataDone',
  '正在等待操作确认': 'userPages.dialogue.awaitingConfirmation',
};

export function localizeStatus(text: string, t: (key: MessageKey) => string) {
  const key = statusKeyByText[text.trim()];
  return key ? t(key) : text;
}

export function plainAssistantMessage(text = '正在思考...'): ChatMessage {
  // The reasoning/tool trace is delivered on dedicated stream/history channels, so the assistant
  // text is rendered as-is. We never split "process" out of the answer text (that was lossy).
  return {
    role: 'assistant',
    sourceCount: 0,
    traceItems: [{ kind: 'thinking', id: 'status:initial', text: '正在连接智能体，准备分析问题' }],
    markdown: normalizeMarkdownForDisplay(text),
  };
}

export const chineseSectionNumber = '[一二三四五六七八九十]+';
export const inlineSubheadingPattern =
  '(核心关键词|长尾关键词|场景词|竞品词|标题结构|标题建议|标题公式|示例方向|五点卖点建议|五点描述|卖点描述|图片\\/A\\+重点|Search Terms|图片和视频|合规提醒|广告策略|预算建议|落地步骤)';
export const sellingPointPattern = '(第一条|第二条|第三条|第四条|第五条)';
export const STREAM_IDLE_TIMEOUT_MS = 180_000;

export class StreamTimeoutError extends Error {
  constructor(message = 'Stream response timed out') {
    super(message);
    this.name = 'StreamTimeoutError';
  }
}

export class StreamEofError extends Error {
  constructor(message = 'Stream ended without a terminal event') {
    super(message);
    this.name = 'StreamEofError';
  }
}

export function stripControlMarkers(text: string) {
  return text
    .replace(/\[\/?(tool|tool_call|tool_result|function|function_call|assistant|system|user)\b[^\]]*\]/gi, '')
    .replace(/<\/?(tool|tool_call|tool_result|function|function_call)\b[^>]*>/gi, '');
}

export function stripWrappingMarkdown(text: string) {
  return text
    .trim()
    .replace(/^\*\*([\s\S]+)\*\*$/, '$1')
    .replace(/^__([\s\S]+)__$/, '$1')
    .trim();
}

export function cleanInlineText(text: string) {
  return text.replace(/\*\*/g, '').replace(/__/g, '');
}

export function splitDenseNumberedItems(line: string) {
  const trimmed = line.trim();
  if (/^\\?#{1,6}\s*.+/.test(trimmed)) {
    return [trimmed];
  }

  return line
    .replace(new RegExp(`\\*\\*(${chineseSectionNumber}[、.]\\s*[^*\\n]{2,40}?)\\*\\*`, 'g'), '\n$1\n')
    .replace(new RegExp(`__(${chineseSectionNumber}[、.]\\s*[^_\\n]{2,40}?)__`, 'g'), '\n$1\n')
    .replace(new RegExp(`([^\\n])\\s*(?=(${chineseSectionNumber}[、.]\\s*))`, 'g'), '$1\n')
    .replace(/\s+(?=\d+[.)]\s+)/g, '\n')
    .replace(new RegExp(`\\s+(?=(${inlineSubheadingPattern})[:：])`, 'gi'), '\n')
    .replace(new RegExp(`\\s+(?=(${sellingPointPattern}写))`, 'g'), '\n')
    .replace(/\s+(?=(核心原则|核心建议|建议|结论|执行方案|营销策略|Listing\s*策略))/gi, '\n')
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean);
}

export function normalizeMarkdownForDisplay(text: string) {
  const normalized = stripControlMarkers(text).replace(/\r\n/g, '\n').trim();
  if (!normalized) {
    return '正在思考...';
  }

  const output: string[] = [];
  const codeLines: string[] = [];
  let inCodeBlock = false;

  for (const sourceLine of normalized.split('\n')) {
    const sourceTrimmed = sourceLine.trim();

    if (sourceTrimmed.startsWith('```')) {
      if (inCodeBlock) {
        output.push(codeLines.join('\n'));
        codeLines.length = 0;
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
      }
      output.push(sourceLine);
      continue;
    }

    if (inCodeBlock) {
      codeLines.push(sourceLine);
      continue;
    }

    const lines = sourceTrimmed ? splitDenseNumberedItems(sourceLine) : [''];

    for (const rawLine of lines) {
      const line = rawLine.trim();

      if (!line || isTracePlaceholder(line)) {
        output.push('');
        continue;
      }

      const markdownHeading = line.match(/^\\?(#{1,6})\s*(.+)$/);
      if (markdownHeading) {
        // Always emit a space after the hashes so `#标题` (common in CN output) renders as a heading.
        output.push(`${markdownHeading[1]} ${stripWrappingMarkdown(markdownHeading[2])}`);
        continue;
      }

      const cleanLine = stripWrappingMarkdown(line);
      const chineseSection = cleanLine.match(new RegExp(`^(${chineseSectionNumber}[、.]\\s*[^:：，。,;；]{2,28}?)(?:\\s+(.+))?$`, 'i'));
      if (chineseSection) {
        output.push(`## ${chineseSection[1].trim()}`);
        if (chineseSection[2]?.trim()) {
          output.push(normalizeInlineSubheading(chineseSection[2].trim()));
        }
        continue;
      }

      if (new RegExp(`^(${inlineSubheadingPattern})[:：]`, 'i').test(line)) {
        output.push(normalizeInlineSubheading(line));
        continue;
      }

      const sellingPoint = line.match(new RegExp(`^(${sellingPointPattern}写[^，。,;；：:]{2,24})(?:\\s+(.+))?$`));
      if (sellingPoint) {
        const title = sellingPoint[1].trim();
        const rest = sellingPoint[2]?.trim();
        output.push(rest ? `- **${title}**：${cleanInlineText(rest)}` : `- **${title}**`);
        continue;
      }

      output.push(cleanInlineText(line));
    }
  }

  if (codeLines.length) {
    output.push(codeLines.join('\n'));
  }

  return compactSellingPointBlocks(compactAudienceTargetingBlocks(output)).join('\n\n').replace(/\n{3,}/g, '\n\n').trim();
}

export function normalizeInlineSubheading(text: string) {
  const inlineSubheading = text.match(new RegExp(`^(${inlineSubheadingPattern})[:：]\\s*(.*)$`, 'i'));
  if (!inlineSubheading) return cleanInlineText(text);

  const rest = inlineSubheading[2]?.trim();
  return rest ? `### ${inlineSubheading[1]}：\n\n${cleanInlineText(rest)}` : `### ${inlineSubheading[1]}：`;
}

export function compactAudienceTargetingBlocks(lines: string[]) {
  const compacted: string[] = [];

  for (let index = 0; index < lines.length; index += 1) {
    const current = lines[index]?.trim() ?? '';
    const next = lines[index + 1]?.trim() ?? '';

    if (isAudienceLabel(current) && isAudienceDescription(next)) {
      compacted.push(`- **${current}**：${next.replace(/^主打\s*/, '')}`);
      index += 1;
      continue;
    }

    compacted.push(lines[index]);
  }

  return compacted;
}

export function isAudienceLabel(text: string) {
  if (!text || text.startsWith('#') || text.startsWith('- ') || text.length > 18) return false;
  return /人群$/.test(text);
}

export function isAudienceDescription(text: string) {
  return /^主打\s+/.test(text);
}

export function mergeTraceText(current: string, incoming: string) {
  const next = incoming.trim();
  if (!next) return current;
  if (!current) return next;
  if (next === current || current.includes(next)) return current;
  if (next.includes(current)) return next;
  return `${current}${incoming}`;
}

export function findLastTraceIndex(items: AssistantTraceItem[], kind: AssistantTraceItem['kind']) {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    if (items[index]?.kind === kind) return index;
  }

  return -1;
}

export function findTraceIndex(items: AssistantTraceItem[], item: AssistantTraceItem) {
  if (item.id) {
    return items.findIndex((trace) => trace.id === item.id);
  }

  const initialStatusIndex = items.findIndex((trace) => trace.id === 'status:initial' && trace.kind === item.kind);
  if (initialStatusIndex >= 0) return initialStatusIndex;

  return findLastTraceIndex(items, item.kind);
}

export function isTracePlaceholder(text: string) {
  const value = text.trim();
  return value === '正在思考...' || value === '正在整理回答...' || value === '正在组织最终回答。';
}

export function appendUniqueTraceItems(target: AssistantTraceItem[], items: AssistantTraceItem[]) {
  items.forEach((item) => {
    const text = normalizeTraceText(item.text);
    if (!text || isTracePlaceholder(text)) return;

    if (item.id && target.some((existing) => existing.id === item.id && existing.text === text)) return;
    if (!item.id && target.some((existing) => existing.kind === item.kind && existing.text === text)) return;

    target.push({ ...item, text });
  });
}

export function normalizeTraceText(text: string) {
  const stripped = stripControlMarkers(text).replace(/\r\n/g, '\n').trim();
  if (!stripped || /^tool$/i.test(stripped)) return '';
  return stripped;
}

export function splitTraceText(text: string): AssistantTraceItem[] {
  return splitProcessSentences(text)
    .map(normalizeTraceText)
    .filter(Boolean)
    .map((line) => ({
      kind: /搜索|检索|读取|调用|查询|知识库|source|sources|工具|tool/i.test(line) ? 'action' as const : 'thinking' as const,
      text: line,
    }));
}

export function compactSellingPointBlocks(lines: string[]) {
  const compacted: string[] = [];

  for (let index = 0; index < lines.length; index += 1) {
    const current = lines[index]?.trim() ?? '';
    const next = lines[index + 1]?.trim() ?? '';

    if (/^-\s+\*\*(第一条|第二条|第三条|第四条|第五条)写/.test(current) && next && !next.startsWith('#') && !next.startsWith('- ')) {
      compacted.push(`${current}：${next}`);
      index += 1;
      continue;
    }

    compacted.push(lines[index]);
  }

  return compacted;
}

export function splitProcessSentences(text: string) {
  return text
    .replace(/\r\n/g, '\n')
    .split(/(?<=[。！？.!?])\s+|\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
}

export function getSessionId(session: ChatSession | null) {
  return String(session?.id ?? session?.sessionId ?? session?.chatId ?? '');
}

export function unwrapCreatedSession(response: Awaited<ReturnType<typeof createChatSession>>): ChatSession | null {
  if (!response) return null;
  if ('data' in response && response.data) return response.data;
  return response;
}

export function parseSseMessage(raw: string) {
  let event = 'message';
  let id: number | null = null;
  const data: string[] = [];

  raw.split('\n').forEach((line) => {
    if (line.startsWith('id:')) {
      const parsed = parseInt(line.slice('id:'.length).trim(), 10);
      if (!isNaN(parsed)) id = parsed;
    }

    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim();
    }

    if (line.startsWith('data:')) {
      data.push(line.slice('data:'.length).trimStart());
    }
  });

  return { id, event, data: data.join('\n') };
}

export function parseSseJson(data: string) {
  if (!data || data === '[DONE]') return null;

  try {
    return JSON.parse(data) as Record<string, unknown>;
  } catch {
    return { text: data };
  }
}

export function readTextDelta(payload: Record<string, unknown> | null) {
  if (!payload) return '';

  const candidates = [
    payload.text,
    payload.delta,
    (payload.delta as { content?: unknown; text?: unknown } | undefined)?.content,
    (payload.delta as { content?: unknown; text?: unknown } | undefined)?.text,
  ];

  const value = candidates.find((candidate) => typeof candidate === 'string');
  return typeof value === 'string' ? value : '';
}

export function readTraceText(payload: Record<string, unknown> | null) {
  if (!payload) return '';

  const candidates = [
    payload.text,
    payload.delta,
    payload.message,
    payload.output,
    payload.content,
    payload.name,
    (payload.delta as { content?: unknown; text?: unknown } | undefined)?.content,
    (payload.delta as { content?: unknown; text?: unknown } | undefined)?.text,
    (payload.data as { text?: unknown; message?: unknown; name?: unknown } | undefined)?.text,
    (payload.data as { text?: unknown; message?: unknown; name?: unknown } | undefined)?.message,
    (payload.data as { text?: unknown; message?: unknown; name?: unknown } | undefined)?.name,
  ];

  const value = candidates.find((candidate) => typeof candidate === 'string');
  return typeof value === 'string' ? value : '';
}

export function readToolProgress(payload: Record<string, unknown> | null): AssistantTraceItem | null {
  if (!payload) return null;

  const toolCallId = typeof payload.toolCallId === 'string' ? payload.toolCallId : undefined;
  const status = typeof payload.status === 'string' ? payload.status : '';
  const title = typeof payload.title === 'string' ? payload.title : '';
  const label = inferToolProgressLabel(title, status);

  return {
    kind: 'action',
    id: toolCallId ? `tool:${toolCallId}` : undefined,
    text: label,
  };
}

export function inferToolProgressLabel(title: string, status: string) {
  const isCompleted = status === 'completed' || status === 'succeeded' || status === 'success';
  const lowerTitle = title.toLowerCase();
  const isKnowledgeBase =
    lowerTitle.includes('knowledge') ||
    lowerTitle.includes('/usr/local/knowledge') ||
    lowerTitle.includes('knowledge-base') ||
    lowerTitle.includes('wiki');

  if (isKnowledgeBase) {
    return isCompleted ? '已完成知识库检索' : '正在检索知识库';
  }

  if (title) {
    return isCompleted ? '已完成工具执行' : '正在执行工具';
  }

  return isCompleted ? '已完成资料处理' : '正在处理资料';
}

export function readToolCallId(payload: Record<string, unknown> | null) {
  if (!payload) return '';

  const data =
    (payload.data as { id?: unknown; toolCallId?: unknown; tool_call_id?: unknown; callId?: unknown } | undefined) ??
    undefined;
  const candidates = [
    payload.toolCallId,
    payload.tool_call_id,
    payload.callId,
    payload.id,
    data?.id,
    data?.toolCallId,
    data?.tool_call_id,
    data?.callId,
  ];
  const value = candidates.find((candidate) => typeof candidate === 'string' && candidate);
  return typeof value === 'string' ? value : '';
}

export function readToolName(payload: Record<string, unknown> | null) {
  if (!payload) return '';

  const data = (payload.data as { title?: unknown; name?: unknown; toolName?: unknown; tool?: unknown } | undefined) ?? undefined;
  const toolObject = (payload.tool as { name?: unknown; title?: unknown } | undefined) ?? undefined;
  const candidates = [
    payload.title,
    payload.name,
    payload.toolName,
    toolObject?.title,
    toolObject?.name,
    data?.title,
    data?.name,
    data?.toolName,
    data?.tool,
  ];
  const value = candidates.find((candidate) => typeof candidate === 'string' && candidate);
  return typeof value === 'string' ? value.trim() : '';
}

// Map a tool event to a friendly label. Never surface the raw tool identifier (e.g. "tool").
export function describeToolActivity(name: string, completed: boolean) {
  return inferToolProgressLabel(name, completed ? 'completed' : 'running');
}

export function buildToolTraceItem(payload: Record<string, unknown> | null, completed: boolean): AssistantTraceItem {
  const toolCallId = readToolCallId(payload);
  const toolName = readToolName(payload);
  const fallbackId = toolName ? `tool:fallback:${toolName.toLowerCase()}` : 'tool:fallback:activity';

  return {
    kind: 'action',
    id: toolCallId ? `tool:${toolCallId}` : fallbackId,
    text: describeToolActivity(toolName, completed),
  };
}

export function readSourceCount(payload: Record<string, unknown> | null) {
  if (!payload) return null;

  const documents = payload.documents;
  return Array.isArray(documents) ? documents.length : null;
}

export function readSources(payload: Record<string, unknown> | null): CitationSource[] {
  if (!payload) return [];

  const raw = payload.documents;
  if (!Array.isArray(raw)) return [];
  return normalizeCitationItems(raw);
}

export function readErrorMessage(payload: Record<string, unknown> | null) {
  if (!payload) return '';

  const candidates = [
    payload.message,
    payload.error,
    payload.detail,
    payload.reason,
    (payload.data as { message?: unknown; error?: unknown; detail?: unknown } | undefined)?.message,
    (payload.data as { message?: unknown; error?: unknown; detail?: unknown } | undefined)?.error,
    (payload.data as { message?: unknown; error?: unknown; detail?: unknown } | undefined)?.detail,
  ];

  const value = candidates.find((candidate) => typeof candidate === 'string' && candidate.trim());
  return typeof value === 'string' ? value.trim() : '';
}

export function getMessageList(response: Awaited<ReturnType<typeof getChatSessionMessages>> | undefined): ChatSessionMessage[] {
  if (!response) return [];
  if (Array.isArray(response)) return response;

  if ('messages' in response && Array.isArray(response.messages)) return response.messages;
  if ('items' in response && Array.isArray(response.items)) return response.items;
  if ('records' in response && Array.isArray(response.records)) return response.records;
  if (!('data' in response)) return [];

  const data = response.data;
  if (Array.isArray(data)) return data;
  if (!data) return [];

  const nestedData = data as {
    messages?: ChatSessionMessage[];
    items?: ChatSessionMessage[];
    records?: ChatSessionMessage[];
  };

  if (Array.isArray(nestedData.messages)) return nestedData.messages;
  if (Array.isArray(nestedData.items)) return nestedData.items;
  if (Array.isArray(nestedData.records)) return nestedData.records;

  return [];
}

export function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

export function readHistoryEventName(record: Record<string, unknown>) {
  const candidates = [record.event, record.type, record.name, record.eventType, record.event_type, record.kind];
  const value = candidates.find((candidate) => typeof candidate === 'string' && candidate.trim());
  return typeof value === 'string' ? value.trim() : '';
}

export function getHistoryEventPayload(record: Record<string, unknown>) {
  const data = asRecord(record.data);
  return data ? { ...record, ...data } : record;
}

export function traceItemFromHistoryEvent(event: unknown): AssistantTraceItem[] {
  if (typeof event === 'string') return splitTraceText(event);

  const record = asRecord(event);
  if (!record) return [];

  const eventName = readHistoryEventName(record);
  const payload = getHistoryEventPayload(record);

  if (eventName === 'tool_call_update') {
    const item = readToolProgress(payload);
    return item ? [item] : [];
  }

  if (eventName === 'tool_call' || eventName === 'tool_result') {
    return [buildToolTraceItem(payload, eventName === 'tool_result')];
  }

  if (
    eventName === 'reasoning_delta' ||
    eventName === 'reasoning' ||
    eventName === 'thinking' ||
    eventName === 'thought' ||
    eventName === 'retrieval' ||
    eventName === 'citation' ||
    eventName === 'sources'
  ) {
    return splitTraceText(readTraceText(payload));
  }

  const text = readTraceText(payload);
  if (text) return splitTraceText(text);

  return [];
}

export function getHistoryEventItems(message: ChatSessionMessage) {
  const metadata = message.metadata;
  const candidates = [
    message.events,
    message.traceEvents,
    message.trace_events,
    message.traces,
    message.trace,
    message.steps,
    Array.isArray(message.reasoning) ? message.reasoning : undefined,
    Array.isArray(metadata?.events) ? metadata.events : undefined,
    Array.isArray(metadata?.traceEvents) ? metadata.traceEvents : undefined,
    Array.isArray(metadata?.trace_events) ? metadata.trace_events : undefined,
    Array.isArray(metadata?.traces) ? metadata.traces : undefined,
    Array.isArray(metadata?.trace) ? metadata.trace : undefined,
    Array.isArray(metadata?.steps) ? metadata.steps : undefined,
  ];

  return candidates.flatMap((candidate) => Array.isArray(candidate) ? candidate.flatMap(traceItemFromHistoryEvent) : []);
}

export function getHistoryTraceItems(message: ChatSessionMessage, reasoningText: string) {
  const traceItems: AssistantTraceItem[] = [];

  appendUniqueTraceItems(traceItems, reasoningText ? splitTraceText(reasoningText) : []);
  appendUniqueTraceItems(traceItems, getHistoryEventItems(message));

  return traceItems;
}

export function normalizeHistoryMessage(message: ChatSessionMessage): ChatMessage[] {
  const requestText = message.requestText || message.request_text || '';
  const responseText = message.responseText || message.response_text || '';
  const reasoningText = message.reasoningText || message.reasoning_text || '';
  const status = String(message.status || '').toLowerCase();
  const errorMessage = message.errorMessage || message.error_message || '';
  const turnId = message.turnId || (typeof message.id === 'string' ? message.id : undefined);

  if (requestText || responseText) {
    const messages: ChatMessage[] = [];

    if (requestText) {
      messages.push({
        role: 'user',
        text: requestText,
        attachments: message.attachments?.length ? message.attachments : undefined,
      });
    }

    const sources = historySources(message);
    const sourceCount = sources.length || (Array.isArray(message.citations) ? message.citations.length : 0);
    const turnAttachments = message.attachments?.length ? message.attachments : undefined;

    if (status === 'failed') {
      if (responseText) {
        messages.push({
          role: 'assistant',
          turnId,
          sourceCount,
          sources: sources.length ? sources : undefined,
          traceItems: getHistoryTraceItems(message, reasoningText),
          markdown: normalizeMarkdownForDisplay(responseText),
          isFailed: true,
          errorText: errorMessage,
          turnAttachments,
        });
      } else {
        messages.push({
          role: 'assistant',
          turnId,
          sourceCount,
          sources: sources.length ? sources : undefined,
          traceItems: [],
          markdown: errorMessage || '问答失败',
          isError: true,
          turnAttachments,
        });
      }
    } else if (status === 'cancelled') {
      if (responseText) {
        messages.push({
          role: 'assistant',
          turnId,
          sourceCount,
          sources: sources.length ? sources : undefined,
          traceItems: getHistoryTraceItems(message, reasoningText),
          markdown: normalizeMarkdownForDisplay(responseText),
          isStopped: true,
          turnAttachments,
        });
      } else {
        messages.push({
          role: 'assistant',
          turnId,
          sourceCount,
          sources: sources.length ? sources : undefined,
          traceItems: [],
          markdown: '已停止',
          turnAttachments,
        });
      }
    } else if (status === 'running') {
      // Still generating — show partial text and mark as streaming for recovery
      messages.push({
        role: 'assistant',
        turnId,
        eventSeq: typeof message.eventSeq === 'number' ? message.eventSeq : undefined,
        isStreaming: true,
        sourceCount,
        sources: sources.length ? sources : undefined,
        traceItems: getHistoryTraceItems(message, reasoningText),
        markdown: responseText ? normalizeMarkdownForDisplay(responseText) : '正在思考...',
        turnAttachments,
      });
    } else if (responseText) {
      messages.push({
        role: 'assistant',
        turnId,
        sourceCount,
        sources: sources.length ? sources : undefined,
        traceItems: getHistoryTraceItems(message, reasoningText),
        markdown: normalizeMarkdownForDisplay(responseText),
        turnAttachments,
      });
    }

    return messages;
  }

  const content = message.content || message.text || '';
  if (!content) return [];

  const role = String(
    message.role || message.sender || message.senderType || message.sender_type || '',
  ).toLowerCase();

  if (role === 'user' || role === 'human') {
    return [{
      role: 'user',
      text: content,
      attachments: message.attachments?.length ? message.attachments : undefined,
    }];
  }

  const sources = historySources(message);
  const turnAttachments = message.attachments?.length ? message.attachments : undefined;
  return [
    {
      role: 'assistant',
      turnId,
      sourceCount: sources.length || (Array.isArray(message.citations) ? message.citations.length : 0),
      sources: sources.length ? sources : undefined,
      traceItems: getHistoryTraceItems(message, reasoningText),
      markdown: normalizeMarkdownForDisplay(content),
      turnAttachments,
    },
  ];
}

function historySources(message: ChatSessionMessage): CitationSource[] {
  const record = message as unknown as Record<string, unknown>;
  const raw = Array.isArray(record.retrievalRefs) ? record.retrievalRefs : null;
  if (!raw) return [];
  return normalizeCitationItems(raw);
}

function normalizeCitationItems(raw: unknown[]): CitationSource[] {
  return raw
    .map((item): CitationSource | null => {
      if (item && typeof item === 'object') {
        const record = item as Record<string, unknown>;
        if (typeof record.fileName !== 'string' || !record.fileName) return null;
        return {
          citationId: typeof record.citationId === 'string' ? record.citationId : null,
          citationIds: Array.isArray(record.citationIds)
            ? record.citationIds.filter((value): value is string => typeof value === 'string')
            : [],
          knowledgeBaseId: typeof record.knowledgeBaseId === 'string' ? record.knowledgeBaseId : null,
          knowledgeBaseName: typeof record.knowledgeBaseName === 'string' ? record.knowledgeBaseName : null,
          documentId: typeof record.documentId === 'string' ? record.documentId : null,
          fileName: record.fileName,
          pageNumber: typeof record.pageNumber === 'number' ? record.pageNumber : null,
          mimeType: typeof record.mimeType === 'string' ? record.mimeType : null,
          hitText: typeof record.hitText === 'string' ? record.hitText : null,
          locator: record.locator && typeof record.locator === 'object'
            ? record.locator as Record<string, unknown>
            : {},
          previewUrl: typeof record.previewUrl === 'string' ? record.previewUrl : null,
          downloadUrl: typeof record.downloadUrl === 'string' ? record.downloadUrl : null,
          available: record.available !== false,
        };
      }
      return null;
    })
    .filter((item): item is CitationSource => item !== null);
}
