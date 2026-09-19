import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { ActiveSelection } from '../../hooks/useTextSelection';
import { copyText } from '../../lib/selection';

interface Props {
  selection: ActiveSelection;
  busy?: boolean;
  onExplain: (selection: ActiveSelection) => void;
}

/**
 * Floating actions anchored to the current text selection: "Copy" and
 * "Explain this".
 *
 * Rendered in a portal so the chat's scroll container can never clip it. The
 * card is `position: fixed` (viewport coordinates), and primary-button
 * `mousedown` is prevented so clicking an action does not collapse the DOM
 * selection before the click handler runs (the right button is left alone so
 * the native context menu — and its Copy — still opens).
 */
export function SelectionPopover({ selection, busy, onExplain }: Props) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
    },
    [],
  );

  const center = selection.rect.left + selection.rect.width / 2;
  const left = Math.max(96, Math.min(center, window.innerWidth - 96));
  // Prefer above the selection; when there is no room, drop below the *bottom*
  // of the selection so the popover never covers the highlighted text (which
  // would block dragging/right-clicking it).
  const above = selection.rect.top - 46;
  const top = above >= 8 ? above : selection.rect.top + selection.rect.height + 8;

  const handleCopy = async () => {
    const ok = await copyText(selection.text);
    if (!ok) return;
    setCopied(true);
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 1400);
  };

  return createPortal(
    <div
      data-explain-popover
      style={{ top, left }}
      onMouseDown={(e) => {
        if (e.button === 0) e.preventDefault();
      }}
      className="fixed z-50 -translate-x-1/2"
    >
      <div className="flex items-center gap-1 rounded-full border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] p-0.5 shadow-lg">
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-semibold text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-bg-tertiary)] hover:text-[var(--color-text-primary)]"
        >
          <span aria-hidden="true">⧉</span>
          {copied ? 'Copied' : 'Copy'}
        </button>
        <button
          type="button"
          onClick={() => onExplain(selection)}
          disabled={busy}
          className="flex items-center gap-1.5 whitespace-nowrap rounded-full border border-[var(--color-accent)]/40 px-3 py-1.5 text-xs font-semibold text-[var(--color-accent)] transition-colors hover:bg-[var(--color-accent)] hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          <span aria-hidden="true">✦</span>
          Explain this
        </button>
      </div>
    </div>,
    document.body,
  );
}
