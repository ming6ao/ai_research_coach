import { Children, useEffect, useRef, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import katex from 'katex';
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
        <div className="prose prose-invert prose-lg max-w-none text-base my-4">
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
              p: ({ children }) => <p>{splitMathChildren(children)}</p>,
              li: ({ children }) => <li>{splitMathChildren(children)}</li>,
              h1: ({ children }) => <h1>{splitMathChildren(children)}</h1>,
              h2: ({ children }) => <h2>{splitMathChildren(children)}</h2>,
              h3: ({ children }) => <h3>{splitMathChildren(children)}</h3>,
              h4: ({ children }) => <h4>{splitMathChildren(children)}</h4>,
              strong: ({ children }) => <strong>{splitMathChildren(children)}</strong>,
              em: ({ children }) => <em>{splitMathChildren(children)}</em>,
              blockquote: ({ children }) => (
                <blockquote>{splitMathChildren(children)}</blockquote>
              ),
            }}
          >
            {feedback}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
}

function splitMathChildren(children: ReactNode): ReactNode {
  return Children.map(children, (child) =>
    typeof child === 'string' ? <MathText text={child} /> : child,
  );
}

const MATH_DELIMITERS = [
  { left: '$$', right: '$$', display: true },
  { left: '$', right: '$', display: false },
];

interface MathSegment {
  type: 'text' | 'math';
  value: string;
  display: boolean;
}

function splitMath(text: string): MathSegment[] {
  const segments: MathSegment[] = [];
  let rest = text;
  // eslint-disable-next-line no-constant-condition
  while (true) {
    let next: { left: string; right: string; display: boolean; index: number } | null = null;
    for (const d of MATH_DELIMITERS) {
      const index = rest.indexOf(d.left);
      if (index !== -1 && (next === null || index < next.index)) {
        next = { ...d, index };
      }
    }
    if (next === null) break;
    if (next.index > 0) {
      segments.push({ type: 'text', value: rest.slice(0, next.index), display: false });
      rest = rest.slice(next.index);
    }
    const end = rest.indexOf(next.right, next.left.length);
    if (end === -1) break;
    segments.push({
      type: 'math',
      value: rest.slice(next.left.length, end),
      display: next.display,
    });
    rest = rest.slice(end + next.right.length);
  }
  if (rest !== '') {
    segments.push({ type: 'text', value: rest, display: false });
  }
  return segments;
}

function InlineMath({ latex, display }: { latex: string; display: boolean }) {
  let html: string | null = null;
  try {
    html = katex.renderToString(latex, { throwOnError: false, displayMode: display });
  } catch {
    html = null;
  }
  if (html === null) {
    return <>{latex}</>;
  }
  return <span dangerouslySetInnerHTML={{ __html: html }} />;
}

function MathText({ text }: { text: string }) {
  const segments = splitMath(text);
  if (segments.length === 1 && segments[0].type === 'text') {
    return <>{text}</>;
  }
  return (
    <>
      {segments.map((segment, i) =>
        segment.type === 'math' ? (
          <InlineMath key={i} latex={segment.value} display={segment.display} />
        ) : (
          segment.value
        ),
      )}
    </>
  );
}
