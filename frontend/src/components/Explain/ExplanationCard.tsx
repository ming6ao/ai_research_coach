import { useState } from 'react';
import type { ExplainItem } from '../../stores/explainStore';
import { Markdown } from '../Markdown/Markdown';

interface Props {
  item: ExplainItem;
  onFollowUp: (item: ExplainItem, question: string) => void;
  onRetry: (id: string) => void;
}

/** One explanation in the panel: quoted passage, answer, terms, follow-up. */
export function ExplanationCard({ item, onFollowUp, onRetry }: Props) {
  const [question, setQuestion] = useState('');
  const isFollowUp = Boolean(item.parentId);

  const submitFollowUp = () => {
    if (!question.trim()) return;
    onFollowUp(item, question);
    setQuestion('');
  };

  return (
    <article
      className={`rounded-xl border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-3 ${
        isFollowUp ? 'ml-3 border-l-2 border-l-[var(--color-accent)]/50' : ''
      }`}
    >
      <p className="border-l-2 border-[var(--color-border-default)] pl-2 text-[11px] italic leading-4 text-[var(--color-text-muted)]">
        “{item.selectedText.length > 240 ? `${item.selectedText.slice(0, 237)}…` : item.selectedText}”
      </p>

      {item.question && (
        <p className="mt-2 text-[12px] font-semibold text-[var(--color-text-primary)]">
          {item.question}
        </p>
      )}

      {item.status === 'pending' && (
        <p className="mt-2 animate-pulse text-[12px] text-[var(--color-text-muted)]">
          Explaining…
        </p>
      )}

      {item.status === 'error' && (
        <div className="mt-2 space-y-1.5">
          <p className="text-[12px] text-[var(--color-error)]">
            {item.error || 'Could not generate an explanation.'}
          </p>
          <button
            type="button"
            onClick={() => onRetry(item.id)}
            className="rounded-md border border-[var(--color-border-default)] px-2 py-0.5 text-[11px] text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]"
          >
            Retry
          </button>
        </div>
      )}

      {item.status === 'ok' && (
        <div className="mt-1.5 space-y-2">
          {item.title && (
            <p className="text-[13px] font-semibold text-[var(--color-text-primary)]">
              {item.title}
              {item.cached && (
                <span className="ml-1.5 text-[10px] font-normal text-[var(--color-text-muted)]">
                  previous answer
                </span>
              )}
            </p>
          )}
          {item.answer && <Markdown text={item.answer} />}
          {item.relatedTerms.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {item.relatedTerms.map((t) => (
                <span
                  key={t}
                  className="rounded-full border border-[var(--color-border-default)] px-2 py-0.5 text-[10px] text-[var(--color-text-muted)]"
                >
                  {t}
                </span>
              ))}
            </div>
          )}
          {!isFollowUp && (
            <div className="flex gap-1.5 pt-1">
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') submitFollowUp();
                }}
                placeholder="Ask a follow-up…"
                className="min-w-0 flex-1 rounded-md border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] px-2 py-1 text-[11px] text-[var(--color-text-primary)]"
              />
              <button
                type="button"
                onClick={submitFollowUp}
                disabled={!question.trim()}
                className="rounded-md bg-[var(--color-accent)] px-2 py-1 text-[11px] font-semibold text-white disabled:opacity-40"
              >
                Ask
              </button>
            </div>
          )}
        </div>
      )}
    </article>
  );
}
