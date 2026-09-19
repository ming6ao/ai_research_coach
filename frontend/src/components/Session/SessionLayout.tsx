import { useEffect } from 'react';
import type { ActiveSelection } from '../../hooks/useTextSelection';
import { useTextSelection } from '../../hooks/useTextSelection';
import { useAssessmentStore } from '../../stores/assessmentStore';
import { useExplainStore } from '../../stores/explainStore';
import { ChatView } from '../Chat/ChatView';
import { ExplainPanel } from '../Explain/ExplainPanel';
import { SelectionPopover } from '../Explain/SelectionPopover';

/**
 * Session screen: the coaching conversation/editor on the left and the
 * selection-driven explanation panel on the right. On narrow screens the panel
 * becomes a right-side overlay drawer (see `ExplainPanel`).
 */
export function SessionLayout() {
  const sessionId = useAssessmentStore((s) => s.sessionId);
  const open = useExplainStore((s) => s.open);
  const { selection, tooLong, clear } = useTextSelection();

  useEffect(() => {
    if (sessionId) void useExplainStore.getState().loadForSession(sessionId);
  }, [sessionId]);

  const handleExplain = (sel: ActiveSelection) => {
    if (!sessionId || !sel.taskId) return;
    // Keep the browser selection intact so the candidate can still copy the
    // passage after asking about it; only the popover is dismissed.
    clear();
    void useExplainStore.getState().ask(sessionId, {
      taskId: sel.taskId,
      stepKey: sel.stepKey,
      selectedText: sel.text,
      context: sel.context,
      sourceKind: sel.sourceKind,
    });
  };

  return (
    <div className="relative flex min-h-0 flex-1">
      <div className="relative min-w-0 flex-1">
        <ChatView />
      </div>

      {open ? (
        <ExplainPanel sessionId={sessionId ?? ''} />
      ) : (
        <button
          type="button"
          onClick={() => useExplainStore.getState().openPanel()}
          className="absolute bottom-4 right-3 z-30 flex items-center gap-1.5 rounded-full border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] px-3 py-1.5 text-xs font-semibold text-[var(--color-text-secondary)] shadow-md transition-colors hover:text-[var(--color-accent)]"
        >
          <span aria-hidden="true">✦</span>
          Explain
        </button>
      )}

      {selection && (
        <SelectionPopover selection={selection} onExplain={handleExplain} />
      )}

      {tooLong && (
        <div className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-4 py-2 text-xs text-[var(--color-text-secondary)] shadow-lg">
          That selection is too long to explain — pick a shorter passage.
        </div>
      )}
    </div>
  );
}
