import { createPortal } from 'react-dom';
import type { ActiveSelection } from '../../hooks/useTextSelection';

interface Props {
  selection: ActiveSelection;
  busy?: boolean;
  onExplain: (selection: ActiveSelection) => void;
}

/**
 * Floating "Explain this" action anchored to the current text selection.
 *
 * Rendered in a portal so the chat's scroll container can never clip it. The
 * card is `position: fixed` (viewport coordinates), and `onMouseDown` is
 * prevented so clicking it does not collapse the DOM selection before the
 * click handler runs.
 */
export function SelectionPopover({ selection, busy, onExplain }: Props) {
  const center = selection.rect.left + selection.rect.width / 2;
  const left = Math.max(96, Math.min(center, window.innerWidth - 96));
  const top = selection.rect.top > 56 ? selection.rect.top - 46 : selection.rect.top + 26;

  return createPortal(
    <div
      data-explain-popover
      style={{ top, left }}
      onMouseDown={(e) => e.preventDefault()}
      className="fixed z-50 -translate-x-1/2"
    >
      <button
        type="button"
        onClick={() => onExplain(selection)}
        disabled={busy}
        className="flex items-center gap-1.5 whitespace-nowrap rounded-full border border-[var(--color-accent)]/40 bg-[var(--color-bg-primary)] px-3 py-1.5 text-xs font-semibold text-[var(--color-accent)] shadow-lg transition-colors hover:bg-[var(--color-accent)] hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
      >
        <span aria-hidden="true">✦</span>
        Explain this
      </button>
    </div>,
    document.body,
  );
}
