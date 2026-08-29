import { useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import renderMathInElement from 'katex/dist/contrib/auto-render';
import 'katex/dist/katex.min.css';
import 'highlight.js/styles/vs2015.css';
import { useAssessmentStore } from '../../stores/assessmentStore';
import type { ResultWithFeedback } from '../../stores/assessmentStore';
import { CodeBlock } from '../CodeBlock/CodeBlock';

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
          <p className="text-base">Feedback will appear here after each answer.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-[var(--color-border-default)] px-4 py-2">
        <h3 className="text-base font-semibold text-[var(--color-text-primary)]">
          Feedback
        </h3>
        {results.length > 0 && (
          <span className="text-base text-[var(--color-text-muted)]">
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
            <div className="text-base text-[var(--color-text-muted)]">Evaluating...</div>
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
  entry: ResultWithFeedback;
  index: number;
  isLatest: boolean;
}) {
  const feedbackRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (feedbackRef.current) {
      renderMathInElement(feedbackRef.current, {
        delimiters: [
          { left: '$$', right: '$$', display: true },
          { left: '$', right: '$', display: false },
        ],
      });
    }
  });

  const { result, feedback, prompt, type, skill, userAnswer } = entry;
  const pct = result.max_score > 0 ? (result.score / result.max_score) * 100 : 0;
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
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-base font-semibold text-[var(--color-text-muted)]">
            #{index}
          </span>
          <span className="rounded bg-[var(--color-bg-tertiary)] px-2 py-1 font-mono text-[11px] uppercase text-[var(--color-text-muted)]">
            {type}
          </span>
          <span className="text-base text-[var(--color-text-muted)]">{skill}</span>
        </div>
        <span className={pct === 100 ? 'text-base font-bold text-[var(--color-success)]' : pct >= 50 ? 'text-base font-bold text-[var(--color-warning)]' : 'text-base font-bold text-[var(--color-error)]'}>
          {result.score}/{result.max_score}
        </span>
      </div>

      {/* Score bar */}
      <div className="mb-3 h-2 overflow-hidden rounded-full bg-[var(--color-bg-tertiary)]">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Question prompt */}
      <div className="mb-3 rounded bg-[var(--color-bg-tertiary)] px-4 py-3">
        <p className="text-base text-[var(--color-text-secondary)]">{prompt}</p>
      </div>

      {/* User answer */}
      <div className="mb-3">
        <p className="text-sm font-medium text-[var(--color-text-muted)]">Your answer:</p>
        <div className="mt-2">
          <CodeBlock code={userAnswer ?? ''} />
        </div>
      </div>

      {/* Feedback */}
      {feedback && (
        <div ref={feedbackRef} className="prose prose-invert prose-lg max-w-none text-base my-4">
          <ReactMarkdown
            components={{
              pre({ children }) {
                return <>{children}</>;
              },
              code({ className, children, ...props }) {
                const text = String(children);
                const lang = /language-(\w+)/.exec(className ?? '')?.[1];
                const isBlock = Boolean(lang) || text.includes('\n');
                if (isBlock) {
                  return <CodeBlock code={text} language={lang ?? 'python'} />;
                }
                return (
                  <code
                    className="rounded bg-[var(--color-bg-tertiary)] px-1 py-0.5 font-mono text-[0.9em] text-[var(--color-text-primary)]"
                    {...props}
                  >
                    {children}
                  </code>
                );
              },
            }}
          >
            {feedback}
          </ReactMarkdown>
        </div>
      )}

      {/* Evaluator rationale */}
      {result.rationale && (
        <div className="mt-3 rounded bg-[var(--color-bg-primary)] px-4 py-3">
          <p className="text-sm font-semibold uppercase text-[var(--color-text-muted)]">
            Evaluator
          </p>
          <p className="text-base text-[var(--color-text-secondary)]">
            {result.rationale}
          </p>
        </div>
      )}
    </div>
  );
}
