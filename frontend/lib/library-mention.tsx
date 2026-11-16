'use client';

import { useCallback, useEffect, useState } from 'react';
import { getLibraryFiles, type LibraryFileItem } from '@/lib/api/library';
import { useI18n } from '@/lib/i18n';

// Matches an in-progress "@query" token that the caret sits at the end of: the
// "@" must start the input or follow whitespace, and the query may not contain
// whitespace or another "@". Group 2 is the query typed so far.
const MENTION_RE = /(^|\s)@([^\s@]*)$/;
const MAX_RESULTS = 8;
const DEBOUNCE_MS = 200;

type MentionState = { open: boolean; triggerIndex: number; query: string };

const CLOSED: MentionState = { open: false, triggerIndex: -1, query: '' };

// Drives an "@"-triggered picker over the user's permanent library files for a
// chat composer textarea. Wire `onInput` into the textarea's onChange (after the
// usual setPrompt), call `onKeyDown` first inside the textarea's onKeyDown and
// bail out of the submit handler when it returns true, and render `popover`
// inside the composer (which is `position: relative`).
//
// `excludeIds` hides files already attached so the same file can't be added
// twice. `onSelect` receives the chosen file; the caller attaches it (e.g. via
// `addLibraryFile`).
export function useLibraryMention(opts: {
  value: string;
  onChange: (next: string) => void;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  onSelect: (file: LibraryFileItem) => void;
  excludeIds?: string[];
}) {
  const { value, onChange, textareaRef, onSelect, excludeIds } = opts;
  const { t } = useI18n();

  const [state, setState] = useState<MentionState>(CLOSED);
  const [items, setItems] = useState<LibraryFileItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);

  const excludeSet = new Set(excludeIds ?? []);
  const visibleItems = items.filter((item) => !excludeSet.has(item.id));

  const close = useCallback(() => setState(CLOSED), []);

  // Re-detect the mention token from the current text + caret position.
  const detect = useCallback((text: string, caret: number) => {
    const match = text.slice(0, caret).match(MENTION_RE);
    if (!match) {
      setState(CLOSED);
      return;
    }
    const query = match[2];
    setState({ open: true, triggerIndex: caret - query.length - 1, query });
    setActiveIndex(0);
  }, []);

  const onInput = useCallback(
    (text: string, caret: number) => detect(text, caret),
    [detect],
  );

  // Fetch permanent library files matching the current query (debounced).
  useEffect(() => {
    if (!state.open) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      setLoading(true);
      getLibraryFiles({
        lifecycle: 'permanent',
        keyword: state.query || undefined,
        pageSize: MAX_RESULTS,
        sort: 'updatedAt_desc',
      })
        .then((res) => {
          if (!cancelled) setItems(res.items);
        })
        .catch(() => {
          if (!cancelled) setItems([]);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [state.open, state.query]);

  const pick = useCallback(
    (file: LibraryFileItem) => {
      const el = textareaRef.current;
      const caret = el?.selectionStart ?? value.length;
      // Drop the "@query" token; the file becomes an attachment chip instead of
      // inline text.
      const next = value.slice(0, state.triggerIndex) + value.slice(caret);
      onChange(next);
      onSelect(file);
      setState(CLOSED);
      // Restore the caret to where the mention was.
      requestAnimationFrame(() => {
        const node = textareaRef.current;
        if (node) {
          node.focus();
          node.setSelectionRange(state.triggerIndex, state.triggerIndex);
        }
      });
    },
    [textareaRef, value, state.triggerIndex, onChange, onSelect],
  );

  // Returns true when it consumed the key so the composer skips its own handling
  // (e.g. Enter-to-send).
  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (!state.open || visibleItems.length === 0) {
        if (state.open && event.key === 'Escape') {
          event.preventDefault();
          close();
          return true;
        }
        return false;
      }
      switch (event.key) {
        case 'ArrowDown':
          event.preventDefault();
          setActiveIndex((i) => (i + 1) % visibleItems.length);
          return true;
        case 'ArrowUp':
          event.preventDefault();
          setActiveIndex((i) => (i - 1 + visibleItems.length) % visibleItems.length);
          return true;
        case 'Enter':
        case 'Tab':
          event.preventDefault();
          pick(visibleItems[Math.min(activeIndex, visibleItems.length - 1)]);
          return true;
        case 'Escape':
          event.preventDefault();
          close();
          return true;
        default:
          return false;
      }
    },
    [state.open, visibleItems, activeIndex, pick, close],
  );

  const popover = state.open ? (
    <div className="mention-popover" role="listbox" aria-label={t('userPages.dialogue.mentionTitle')}>
      <p className="mention-popover-title">{t('userPages.dialogue.mentionTitle')}</p>
      {loading && visibleItems.length === 0 ? (
        <p className="mention-popover-empty">{t('userPages.dialogue.mentionLoading')}</p>
      ) : visibleItems.length === 0 ? (
        <p className="mention-popover-empty">{t('userPages.dialogue.mentionEmpty')}</p>
      ) : (
        <ul className="mention-popover-list">
          {visibleItems.map((file, index) => (
            <li key={file.id}>
              <button
                type="button"
                role="option"
                aria-selected={index === activeIndex}
                className={`mention-popover-item ${index === activeIndex ? 'active' : ''}`}
                onMouseDown={(event) => {
                  // Keep textarea focus so caret restoration works.
                  event.preventDefault();
                  pick(file);
                }}
                onMouseEnter={() => setActiveIndex(index)}
              >
                <span className="mention-popover-name" title={file.name}>{file.name}</span>
                <span className="mention-popover-meta">{file.sizeLabel}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  ) : null;

  return { onInput, onKeyDown, popover, close };
}
