import { useEffect, useRef } from 'react';
import { useExplainStore } from '../../stores/explainStore';
import { ExplanationCard } from './ExplanationCard';

interface Props {
  sessionId: string;
}

/** Right-hand explanation pane: a scrollable list of explanation cards. */
export function ExplainPanel({ sessionId }: Props) {
  const items = useExplainStore((s) => s.items);
  const closePanel = useExplainStore((s) => s.closePanel);
  const askFollowUp = useExplainStore((s) => s.askFollowUp);
  const retry = useExplainStore((s) => s.retry);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [items.length]);

  return (
    <aside
      role="complementary"
      aria-label="Explanations"
      className="flex w-[380px] shrink-0 flex-col border-l border-[var(--color-border-default)] bg-[var(--color-bg-primary)] max-lg:fixed max-lg:inset-y-0 max-lg:right-0 max-lg:z-40 max-lg:w-[88vw] max-lg:max-w-sm max-lg:shadow-2xl xl:w-[440px]"
    >
      <header className="flex items-center justify-between border-b border-[var(--color-border-default)] px-4 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-[var(--color-text-primary)]">
          <span aria-hidden="true" className="text-[var(--color-accent)]">✦</span>
          Explain
          {items.length > 0 && (
            <span className="text-[11px] font-normal text-[var(--color-text-muted)]">
              {items.length}
            </span>
          )}
        </h2>
        <button
          type="button"
          onClick={closePanel}
          aria-label="Close explanations"
          className="rounded-md px-2 py-1 text-xs text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text-primary)]"
        >
          ✕
        </button>
      </header>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {items.length === 0 && (
          <p className="rounded-xl border border-dashed border-[var(--color-border-default)] px-3 py-4 text-[12px] leading-5 text-[var(--color-text-muted)]">
            Select any text or equation in the question, coaching, or context and choose
            <span className="font-semibold text-[var(--color-text-secondary)]"> Explain this</span>.
            Explanations appear here.
          </p>
        )}
        {items.map((item) => (
          <ExplanationCard
            key={item.id}
            item={item}
            onFollowUp={(it, q) => void askFollowUp(sessionId, it, q)}
            onRetry={(id) => void retry(sessionId, id)}
          />
        ))}
        <div ref={bottomRef} />
      </div>

      <div aria-live="polite" className="sr-only">
        {items.some((i) => i.status === 'pending') ? 'Generating an explanation' : ''}
      </div>
    </aside>
  );
}
