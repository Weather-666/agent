'use client';

import { useEffect, useRef, useState } from 'react';
import { uploadChatAttachment } from '@/lib/api/library';
import { useI18n } from '@/lib/i18n';
import type { ChatTurnAttachment } from '@/lib/api/chat';

// Mirrors object_storage_max_upload_bytes (100 MiB) so oversized files fail fast client-side.
export const MAX_ATTACHMENT_BYTES = 100 * 1024 * 1024;

export type ChatAttachment = {
  localId: string;
  name: string;
  mimeType?: string;
  sizeLabel?: string;
  fileId?: string;
  status: 'uploading' | 'ready' | 'error';
  previewUrl?: string;
  // Set when the attachment references an existing permanent library file picked
  // via the "@" mention menu rather than a freshly uploaded temporary file.
  fromLibrary?: boolean;
};

// Extends the API attachment type with a local preview URL for images.
export type MessageAttachment = ChatTurnAttachment & {
  previewUrl?: string;
};

export type AttachmentErrorKind = 'tooLarge' | 'auth' | 'failed';

// Shared composer attachment state. Each file is uploaded as a temporary library
// file (created unbound, so uploads work before a chat session exists); the first
// turn that references its id binds it to that session. Used by both the home and
// dialogue composers so a brand-new conversation can attach files too.
export function useChatAttachments(onError?: (kind: AttachmentErrorKind) => void) {
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const seqRef = useRef(0);
  const previewUrlsRef = useRef<Map<string, string>>(new Map());

  const uploadOne = async (file: File) => {
    const localId = `att-${seqRef.current++}`;
    if (file.size > MAX_ATTACHMENT_BYTES) {
      onError?.('tooLarge');
      return;
    }
    const mimeType = file.type || 'application/octet-stream';
    const previewUrl = mimeType.startsWith('image/') ? URL.createObjectURL(file) : undefined;
    if (previewUrl) previewUrlsRef.current.set(localId, previewUrl);

    setAttachments((prev) => [...prev, { localId, name: file.name, mimeType, previewUrl, status: 'uploading' }]);
    try {
      const uploaded = await uploadChatAttachment(file);
      setAttachments((prev) =>
        prev.map((item) =>
          item.localId === localId
            ? { ...item, fileId: uploaded.id, sizeLabel: uploaded.sizeLabel, status: 'ready' }
            : item,
        ),
      );
    } catch (error) {
      const status = (error as { status?: number }).status;
      onError?.(status === 401 ? 'auth' : 'failed');
      setAttachments((prev) =>
        prev.map((item) => (item.localId === localId ? { ...item, status: 'error' } : item)),
      );
    }
  };

  const addFiles = (fileList: FileList | null) => {
    if (!fileList) return;
    Array.from(fileList).forEach((file) => void uploadOne(file));
  };

  // Attach an existing permanent library file (chosen via the "@" mention menu).
  // It is already stored, so it lands as a ready attachment straight away. Files
  // already attached (same fileId) are ignored so a file can't be added twice.
  const addLibraryFile = (file: { id: string; name: string; sizeLabel?: string; mimeType?: string }) => {
    setAttachments((prev) => {
      if (prev.some((item) => item.fileId === file.id)) return prev;
      const localId = `att-${seqRef.current++}`;
      return [
        ...prev,
        { localId, name: file.name, mimeType: file.mimeType, sizeLabel: file.sizeLabel, fileId: file.id, status: 'ready', fromLibrary: true },
      ];
    });
  };

  const removeAttachment = (localId: string) => {
    const url = previewUrlsRef.current.get(localId);
    if (url) {
      URL.revokeObjectURL(url);
      previewUrlsRef.current.delete(localId);
    }
    setAttachments((prev) => prev.filter((item) => item.localId !== localId));
  };

  const clearAttachments = () => setAttachments([]);

  const readyFileIds = attachments
    .filter((item) => item.status === 'ready' && item.fileId)
    .map((item) => item.fileId as string);

  return { attachments, addFiles, addLibraryFile, removeAttachment, clearAttachments, readyFileIds };
}

// ─── Progress ring ────────────────────────────────────────────────────────────

function ProgressRing({ progress, size = 64 }: { progress: number; size?: number }) {
  const radius = 26 * size / 64;
  const circumference = 2 * Math.PI * radius;
  const center = size / 2;
  const offset = circumference * (1 - Math.max(0, Math.min(100, progress)) / 100);
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      style={{ display: 'block', transform: 'rotate(-90deg)' }}
      aria-hidden="true"
    >
      <circle cx={center} cy={center} r={radius} fill="none" stroke="rgba(255,255,255,0.25)" strokeWidth="3.5" />
      <circle
        cx={center}
        cy={center}
        r={radius}
        fill="none"
        stroke="#fff"
        strokeWidth="3.5"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        strokeLinecap="round"
        style={{ transition: 'stroke-dashoffset 0.08s linear' }}
      />
    </svg>
  );
}

// ─── File type badge ──────────────────────────────────────────────────────────

const MIME_BADGE_COLORS: Record<string, string> = {
  'application/pdf': '#e8472f',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '#185abc',
  'application/msword': '#185abc',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '#1e6e42',
  'application/vnd.ms-excel': '#1e6e42',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': '#c44428',
  'application/vnd.ms-powerpoint': '#c44428',
  'application/zip': '#6b7280',
  'application/x-zip-compressed': '#6b7280',
  'application/x-rar-compressed': '#6b7280',
  'application/x-7z-compressed': '#6b7280',
  'text/plain': '#4b5563',
  'text/csv': '#1e6e42',
  'application/json': '#7c3aed',
};

const MIME_BADGE_LABELS: Record<string, string> = {
  'application/pdf': 'PDF',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'DOC',
  'application/msword': 'DOC',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'XLS',
  'application/vnd.ms-excel': 'XLS',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PPT',
  'application/vnd.ms-powerpoint': 'PPT',
  'application/zip': 'ZIP',
  'application/x-zip-compressed': 'ZIP',
  'application/x-rar-compressed': 'RAR',
  'application/x-7z-compressed': '7Z',
  'text/plain': 'TXT',
  'text/csv': 'CSV',
  'application/json': 'JSON',
};

const MIME_LABELS: Record<string, string> = {
  'application/pdf': 'PDF 文档',
  'application/zip': '压缩归档',
  'application/x-zip-compressed': '压缩归档',
  'application/x-rar-compressed': '压缩归档',
  'application/x-7z-compressed': '压缩归档',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'Word 文档',
  'application/msword': 'Word 文档',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'Excel 表格',
  'application/vnd.ms-excel': 'Excel 表格',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PPT 演示文稿',
  'application/vnd.ms-powerpoint': 'PPT 演示文稿',
  'text/plain': '文本文件',
  'text/csv': 'CSV 文件',
  'application/json': 'JSON 文件',
  'image/jpeg': 'JPEG 图片',
  'image/png': 'PNG 图片',
  'image/gif': 'GIF 图片',
  'image/webp': 'WebP 图片',
  'image/svg+xml': 'SVG 图片',
};

function getMimeLabel(mimeType?: string, name?: string): string {
  if (!mimeType) {
    const ext = name?.split('.').pop()?.toLowerCase();
    return ext ? ext.toUpperCase() + ' 文件' : '文件';
  }
  if (MIME_LABELS[mimeType]) return MIME_LABELS[mimeType];
  if (mimeType.startsWith('image/')) return '图片';
  if (mimeType.startsWith('video/')) return '视频';
  if (mimeType.startsWith('audio/')) return '音频';
  if (mimeType.startsWith('text/')) return '文本文件';
  return '文件';
}

function FileBadge({ mimeType, name }: { mimeType?: string; name?: string }) {
  const ext = name?.split('.').pop()?.toUpperCase()?.slice(0, 4) ?? '';
  const label = (mimeType && MIME_BADGE_LABELS[mimeType]) ?? (ext || '···');
  const bgColor = (mimeType && MIME_BADGE_COLORS[mimeType]) ?? '#6b7280';
  return (
    <span className="composer-att-badge" style={{ backgroundColor: bgColor }}>
      {label}
    </span>
  );
}

// ─── Image attachment chip (square thumbnail + progress ring) ─────────────────

function ImageAttachmentChip({ item, onRemove }: { item: ChatAttachment; onRemove: () => void }) {
  const [progress, setProgress] = useState(0);
  const [overlayVisible, setOverlayVisible] = useState(item.status === 'uploading');
  // Track whether we ever showed the overlay so we animate completion only when needed.
  const overlayShownRef = useRef(item.status === 'uploading');

  useEffect(() => {
    let disposed = false;
    if (item.status === 'uploading') {
      overlayShownRef.current = true;
      queueMicrotask(() => {
        if (disposed) return;
        setOverlayVisible(true);
        setProgress(0);
      });
      const start = Date.now();
      const timer = setInterval(() => {
        // Exponential ease-out toward 85% — slows as it approaches the cap.
        setProgress(Math.min(85, 85 * (1 - Math.exp(-(Date.now() - start) / 2800))));
      }, 60);
      return () => {
        disposed = true;
        clearInterval(timer);
      };
    }

    if (overlayShownRef.current) {
      // Upload finished (success or error) — animate to 100% then reveal the image.
      queueMicrotask(() => {
        if (!disposed) setProgress(100);
      });
      const t = setTimeout(() => {
        setOverlayVisible(false);
        overlayShownRef.current = false;
      }, 380);
      return () => {
        disposed = true;
        clearTimeout(t);
      };
    }
    return () => {
      disposed = true;
    };
  }, [item.status]);

  const isError = item.status === 'error';

  return (
    <div className={`composer-att-img-wrap${isError ? ' is-error' : ''}`}>
      {item.previewUrl ? (
        <img src={item.previewUrl} alt={item.name} className="composer-att-img" />
      ) : (
        <div className="composer-att-img composer-att-img-placeholder" />
      )}
      {overlayVisible && (
        <div className="composer-att-overlay">
          <ProgressRing progress={progress} />
        </div>
      )}
      <button
        type="button"
        className="composer-att-remove"
        onClick={onRemove}
        aria-label={`Remove ${item.name}`}
      >
        <svg viewBox="0 0 10 10" width="8" height="8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <line x1="2" y1="2" x2="8" y2="8" />
          <line x1="8" y1="2" x2="2" y2="8" />
        </svg>
      </button>
    </div>
  );
}

// ─── File attachment chip (icon badge + name + type) ──────────────────────────

function FileAttachmentChip({ item, onRemove }: { item: ChatAttachment; onRemove: () => void }) {
  const isError = item.status === 'error';
  const [progress, setProgress] = useState(0);
  const [overlayVisible, setOverlayVisible] = useState(item.status === 'uploading');
  const overlayShownRef = useRef(item.status === 'uploading');

  useEffect(() => {
    let disposed = false;
    if (item.status === 'uploading') {
      overlayShownRef.current = true;
      queueMicrotask(() => {
        if (disposed) return;
        setOverlayVisible(true);
        setProgress(0);
      });
      const start = Date.now();
      const timer = setInterval(() => {
        setProgress(Math.min(85, 85 * (1 - Math.exp(-(Date.now() - start) / 2800))));
      }, 60);
      return () => {
        disposed = true;
        clearInterval(timer);
      };
    }

    if (overlayShownRef.current) {
      queueMicrotask(() => {
        if (!disposed) setProgress(100);
      });
      const t = setTimeout(() => {
        setOverlayVisible(false);
        overlayShownRef.current = false;
      }, 380);
      return () => {
        disposed = true;
        clearTimeout(t);
      };
    }
    return () => {
      disposed = true;
    };
  }, [item.status]);

  return (
    <div className="composer-att-file-wrap">
      <div className={`composer-att-file${isError ? ' is-error' : ''}`}>
        <FileBadge mimeType={item.mimeType} name={item.name} />
        <span className="composer-att-file-info">
          <span className="composer-att-file-name" title={item.name}>{item.name}</span>
          <span className="composer-att-file-meta">
            {isError ? '上传失败' : getMimeLabel(item.mimeType, item.name)}
          </span>
        </span>
        {overlayVisible && (
          <div className="composer-att-file-overlay">
            <ProgressRing progress={progress} size={44} />
          </div>
        )}
      </div>
      <button
        type="button"
        className="composer-att-file-remove"
        onClick={onRemove}
        aria-label={`Remove ${item.name}`}
      >
        <svg viewBox="0 0 10 10" width="8" height="8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <line x1="2" y1="2" x2="8" y2="8" />
          <line x1="8" y1="2" x2="2" y2="8" />
        </svg>
      </button>
    </div>
  );
}

// ─── Composer attachment list (shown inside the composer) ─────────────────────

export function ChatAttachmentChips({
  attachments,
  onRemove,
}: {
  attachments: ChatAttachment[];
  onRemove: (localId: string) => void;
}) {
  const { t } = useI18n();
  if (attachments.length === 0) return null;

  return (
    <ul className="composer-attachments" aria-label={t('userPages.dialogue.attachmentsLabel')}>
      {attachments.map((item) => {
        const isImage = item.mimeType?.startsWith('image/') ?? false;
        return (
          <li key={item.localId} className="composer-attachment-item">
            {isImage ? (
              <ImageAttachmentChip item={item} onRemove={() => onRemove(item.localId)} />
            ) : (
              <FileAttachmentChip item={item} onRemove={() => onRemove(item.localId)} />
            )}
          </li>
        );
      })}
    </ul>
  );
}

// ─── Message attachment list (shown in sent messages) ─────────────────────────

function FileDocIcon() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
  );
}

export function MessageAttachmentList({ attachments }: { attachments?: MessageAttachment[] }) {
  if (!attachments || attachments.length === 0) return null;

  return (
    <ul className="message-attachments">
      {attachments.map((att, i) => {
        const isImage = att.mimeType?.startsWith('image/') ?? false;

        if (isImage && att.previewUrl) {
          return (
            <li key={att.fileId ?? i} className="message-attachment-image">
              <img src={att.previewUrl} alt={att.name ?? '图片'} className="message-attachment-img" />
              {att.name && <span className="message-attachment-img-name">{att.name}</span>}
            </li>
          );
        }

        return (
          <li key={att.fileId ?? i} className="message-attachment-file">
            <span className="message-attachment-file-icon">
              <FileDocIcon />
            </span>
            <span className="message-attachment-file-info">
              <span className="message-attachment-file-name">{att.name || att.fileId}</span>
              <span className="message-attachment-file-type">{getMimeLabel(att.mimeType, att.name)}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}
