import { useState } from 'react';
import { useAssessmentStore } from '../../stores/assessmentStore';

export function ChatLog() {
  const { chatLog } = useAssessmentStore();
  const [expanded, setExpanded] = useState(false);

  if (chatLog.length === 0) return null;

  return (
    <div className="border-t border-[var(--color-border-default)] bg-[var(--color-bg-secondary)]">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-4 py-2 text-xs text-[var(--color-text-muted)] hover:bg-[var(--color-bg-tertiary)]"
      >
        <span className="font-semibold uppercase tracking-wider">
          Activity Log ({chatLog.length})
        </span>
        <span className="text-[var(--color-text-muted)]">
          {expanded ? '▲' : '▼'}
        </span>
      </button>

      {expanded && (
        <div className="max-h-48 overflow-y-auto border-t border-[var(--color-border-default)] px-4 py-2">
          {chatLog.map((entry) => (
            <div
              key={entry.id}
              className="flex items-start gap-2 py-1 font-mono text-xs"
            >
              <span className="shrink-0 text-[var(--color-text-muted)]">
                {entry.timestamp}
              </span>
              <span
                className={
                  entry.message.startsWith('Error')
                    ? 'text-[var(--color-error)]'
                    : entry.message.startsWith('Score')
                      ? 'text-[var(--color-success)]'
                      : 'text-[var(--color-text-secondary)]'
                }
              >
                {entry.message}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
