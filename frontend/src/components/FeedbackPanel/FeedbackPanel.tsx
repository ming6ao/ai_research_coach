import { useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import { useAssessmentStore } from '../../stores/assessmentStore';

export function FeedbackPanel() {
  const { results, loading } = useAssessmentStore();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [results.length]);

  if (results.length === 0 && !loading) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="text-center text-[var(--color-text-muted)]">
          <p className="text-sm">Feedback will appear here after each answer.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-[var(--color-border-default)] px-4 py-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Feedback
        </h3>
        {results.length > 0 && (
          <span className="text-xs text-[var(--color-text-muted)]">
            {results.length} answered
          </span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        {results.map((r, i) => (
          <FeedbackItem key={i} entry={r} index={i + 1} isLatest={i === results.length - 1} />
        ))}

        {loading && (
          <div className="flex items-center justify-center px-4 py-6">
            <div className="text-sm text-[var(--color-text-muted)]">Evaluating...</div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function FeedbackItem({
  entry,
  index,
  isLatest,
}: {
  entry: ReturnType<typeof useAssessmentStore>['results'][number];
  index: number;
  isLatest: boolean;
}) {
  const { result, feedback, prompt, type, skill, userAnswer } = entry;
  const pct = result.max_score > 0 ? (result.score / result.max_score) * 100 : 0;
  const scoreColor =
    pct === 100
      ? 'text-[var(--color-success)]'
      : pct >= 50
        ? 'text-[var(--color-warning)]'
        : 'text-[var(--color-error)]';
  const barColor =
    pct === 100
      ? 'bg-[var(--color-success)]'
      : pct >= 50
        ? 'bg-[var(--color-warning)]'
        : 'bg-[var(--color-error)]';

  return (
    <div
      className={`border-b border-[var(--color-border-default)] p-4 ${
        isLatest ? 'bg-[var(--color-bg-secondary)]' : ''
      }`}
    >
      {/* Header row */}
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-[var(--color-text-muted)]">
            #{index}
          </span>
          <span className="rounded bg-[var(--color-bg-tertiary)] px-1.5 py-0.5 font-mono text-[10px] uppercase text-[var(--color-text-muted)]">
            {type}
          </span>
          <span className="text-[10px] text-[var(--color-text-muted)]">{skill}</span>
        </div>
        <span className={`text-xs font-bold ${scoreColor}`}>
          {result.score}/{result.max_score}
        </span>
      </div>

      {/* Score bar */}
      <div className="mb-3 h-1 overflow-hidden rounded-full bg-[var(--color-bg-tertiary)]">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Question prompt */}
      <div className="mb-2 rounded bg-[var(--color-bg-tertiary)] px-3 py-2">
        <p className="text-xs text-[var(--color-text-secondary)]">{prompt}</p>
      </div>

      {/* User answer */}
      {type === 'mcq' ? (
        <p className="mb-2 text-xs text-[var(--color-text-muted)]">
          Answer: <span className="font-semibold text-[var(--color-text-primary)]">{userAnswer}</span>
        </p>
      ) : (
        <div className="mb-2">
          <p className="mb-1 text-[10px] uppercase text-[var(--color-text-muted)]">Your answer:</p>
          <pre className="max-h-24 overflow-auto rounded bg-[var(--color-bg-primary)] px-3 py-2 font-mono text-[11px] text-[var(--color-text-secondary)]">
            {userAnswer}
          </pre>
        </div>
      )}

      {/* Feedback */}
      {feedback && (
        <div className="prose prose-invert prose-xs max-w-none text-[12px]">
          <ReactMarkdown>{feedback}</ReactMarkdown>
        </div>
      )}

      {/* Evaluator rationale */}
      {result.rationale && (
        <div className="mt-2 rounded bg-[var(--color-bg-primary)] px-3 py-2">
          <p className="mb-0.5 text-[10px] font-semibold uppercase text-[var(--color-text-muted)]">
            Evaluator
          </p>
          <p className="text-[11px] text-[var(--color-text-secondary)]">
            {result.rationale}
          </p>
        </div>
      )}
    </div>
  );
}
