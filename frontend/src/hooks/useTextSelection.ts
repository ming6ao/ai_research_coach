import { useCallback, useEffect, useState } from 'react';
import type { ExplainBody } from '../api/client';
import { MAX_SELECTION, clampContext, serializeRange } from '../lib/selection';

export interface ActiveSelection {
  text: string;
  context: string;
  sourceKind: ExplainBody['source_kind'];
  taskId: string;
  stepKey?: string;
  /** Viewport-relative anchor rect (top center of the selection). */
  rect: { top: number; left: number; width: number };
}

export interface TextSelectionState {
  selection: ActiveSelection | null;
  /** True when the highlight exceeds MAX_SELECTION (popover shows a notice). */
  tooLong: boolean;
  clear: () => void;
}

const ALLOWED_KINDS = new Set<ExplainBody['source_kind']>([
  'question',
  'coaching',
  'context',
  'code',
  'other',
]);

function nearestSelectable(node: Node | null): HTMLElement | null {
  if (!node) return null;
  const el = node.nodeType === Node.ELEMENT_NODE ? (node as Element) : node.parentElement;
  return (el?.closest('[data-selectable]') as HTMLElement | null) ?? null;
}

/**
 * Watches the document for a non-collapsed selection inside a
 * ``[data-selectable]`` region and exposes it for the "Explain this" popover.
 *
 * Only one hook instance should be mounted (``SessionLayout``). It ignores
 * events originating inside the popover itself so clicking the action does not
 * immediately dismiss the selection.
 */
export function useTextSelection(): TextSelectionState {
  const [selection, setSelection] = useState<ActiveSelection | null>(null);
  const [tooLong, setTooLong] = useState(false);

  const clear = useCallback(() => {
    setSelection(null);
    setTooLong(false);
  }, []);

  useEffect(() => {
    const onUp = (event: Event) => {
      const target = event.target as Element | null;
      if (target?.closest?.('[data-explain-popover]')) return;
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || sel.rangeCount === 0) {
        clear();
        return;
      }
      const range = sel.getRangeAt(0);
      const region = nearestSelectable(range.commonAncestorContainer);
      if (!region) {
        clear();
        return;
      }
      const text = serializeRange(range);
      if (!text) {
        clear();
        return;
      }
      if (text.length > MAX_SELECTION) {
        setSelection(null);
        setTooLong(true);
        return;
      }
      const rect = range.getBoundingClientRect();
      if (!rect || (rect.width === 0 && rect.height === 0)) {
        clear();
        return;
      }
      const rawKind = region.dataset.sourceKind ?? 'other';
      const sourceKind = (ALLOWED_KINDS.has(rawKind as ExplainBody['source_kind'])
        ? rawKind
        : 'other') as ExplainBody['source_kind'];
      const container = range.commonAncestorContainer;
      const el =
        container.nodeType === Node.ELEMENT_NODE
          ? (container as Element)
          : container.parentElement;
      const block = el?.closest('p, li, blockquote, h1, h2, h3, h4') as HTMLElement | null;
      const contextSource = block ?? region;
      setTooLong(false);
      setSelection({
        text,
        context: clampContext(contextSource.textContent ?? ''),
        sourceKind,
        taskId: region.dataset.taskId ?? '',
        stepKey: region.dataset.stepKey || undefined,
        rect: { top: rect.top, left: rect.left, width: rect.width },
      });
    };

    const onSelectionChange = () => {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed) clear();
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') clear();
    };

    document.addEventListener('mouseup', onUp);
    document.addEventListener('keyup', onUp);
    document.addEventListener('selectionchange', onSelectionChange);
    document.addEventListener('keydown', onKeyDown);
    window.addEventListener('scroll', clear, true);
    window.addEventListener('resize', clear);
    return () => {
      document.removeEventListener('mouseup', onUp);
      document.removeEventListener('keyup', onUp);
      document.removeEventListener('selectionchange', onSelectionChange);
      document.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('scroll', clear, true);
      window.removeEventListener('resize', clear);
    };
  }, [clear]);

  return { selection, tooLong, clear };
}
