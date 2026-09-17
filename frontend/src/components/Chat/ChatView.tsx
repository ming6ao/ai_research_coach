import { Fragment, useEffect, useRef, useState } from 'react';
import { useAssessmentStore, type ResultWithFeedback } from '../../stores/assessmentStore';
import { apiClient } from '../../api/client';
import { CodeEditor } from '../TaskPanel/CodeEditor';
import { Markdown } from '../Markdown/Markdown';
import { Composer } from '../Composer/Composer';
import { CodeBlock } from '../CodeBlock/CodeBlock';
import { CoachBubble, QuestionBubble } from '../Task/QuestionBubble';

const NOTE_SEPARATOR = '\n\n---\n';

function verdictFor(r: ResultWithFeedback): { label: string; cls: string } | null {
  const max = r.result.max_score;
  if (!max) return null;
  const fraction = r.result.score / max;
  if (fraction >= 0.8) return { label: 'Correct', cls: 'bg-[var(--color-success)]/15 text-[var(--color-success)]' };
  if (fraction <= 0.4) return { label: 'Incorrect', cls: 'bg-[var(--color-error)]/15 text-[var(--color-error)]' };
  return { label: 'Partially correct', cls: 'bg-[var(--color-warning)]/15 text-[var(--color-warning)]' };
}

function splitNote(answer: string): { code: string; note: string } {
  const idx = answer.indexOf(NOTE_SEPARATOR);
  if (idx === -1) return { code: answer, note: '' };
  return { code: answer.slice(0, idx), note: answer.slice(idx + NOTE_SEPARATOR.length).trim() };
}

function UserTextBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%]">
        <div className="mb-1 text-right text-[11px] text-[var(--color-text-muted)]">You</div>
        <div className="rounded-2xl rounded-tr-sm bg-[var(--color-accent)] px-4 py-3 text-[13px] leading-5 text-white">
          {text}
        </div>
      </div>
    </div>
  );
}

function UserCodeBubble({ answer, language }: { answer: string; language?: string }) {
  const { code, note } = splitNote(answer);
  return (
    <div className="space-y-2">
      <CodeEditor code={code} language={language} readOnly />
      {note && <UserTextBubble text={note} />}
    </div>
  );
}

function shortGapText(coach: ResultWithFeedback['coach']): string {
  const raw = (coach?.feedback || coach?.misconception || '').trim();
  if (!raw) return '';
  const first = raw.match(/^.*?[.!?](\s|$)/)?.[0]?.trim() ?? raw;
  const singleLine = first.replace(/\s+/g, ' ');
  return singleLine.length > 120 ? `${singleLine.slice(0, 117).trimEnd()}…` : singleLine;
}

/** Per-part outcomes (a phased task has one active part). */
function PartResults({ r }: { r: ResultWithFeedback }) {
  const parts = r.result.parts;
  if (!parts || parts.length === 0) return null;
  return (
    <ul className="space-y-1.5">
      {parts.map((p) => {
        const part = r.parts?.find((x) => x.key === p.key);
        const max = part?.max_score ?? 5;
        const pct = max ? Math.round((p.score / max) * 100) : 0;
        const tone =
          pct >= 80
            ? 'text-[var(--color-success)]'
            : pct <= 40
              ? 'text-[var(--color-error)]'
              : 'text-[var(--color-warning)]';
        return (
          <li
            key={p.key}
            className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-2.5 py-1.5"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="min-w-0 truncate font-mono text-[12px] text-[var(--color-text-primary)]">
                {p.key}
              </span>
              <span className={`shrink-0 text-[11px] font-semibold ${tone}`}>
                {p.score}/{max} · {pct}%
              </span>
            </div>
            {p.rationale && (
              <p className="mt-0.5 text-[11px] leading-4 text-[var(--color-text-muted)]">{p.rationale}</p>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function CoachingBubble({ r }: { r: ResultWithFeedback }) {
  const coach = r.coach;
  const verdict = verdictFor(r);
  const gap = shortGapText(coach);
  return (
    <CoachBubble wide>
      <div className="space-y-3">
        <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          {verdict && (
            <span className={`rounded-full px-2 py-0.5 text-[10px] ${verdict.cls}`}>
              {verdict.label}{gap ? ` — ${gap}` : ''}
            </span>
          )}
        </p>
        <PartResults r={r} />
        {coach && coach.steps.length > 0 ? (
          <ol className="space-y-3">
            {coach.steps.map((step, i) => (
              <li key={i} className="space-y-1.5">
                <p className="text-sm font-semibold text-[var(--color-text-primary)]">
                  {i + 1}. {step.title}
                </p>
                {step.explanation && <Markdown text={step.explanation} />}
                {step.code && <CodeBlock code={step.code} />}
              </li>
            ))}
          </ol>
        ) : (
          <Markdown text={r.feedback} />
        )}
      </div>
    </CoachBubble>
  );
}

function DoneBubble() {
  const { completeSession, loading } = useAssessmentStore();
  return (
    <CoachBubble>
      <p className="mb-3 text-sm text-[var(--color-text-primary)]">
        No further questions are available right now. You can review your progress or start a new session.
      </p>
      <button
        onClick={completeSession}
        disabled={loading}
        className="rounded-lg bg-[var(--color-accent)] px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-40"
      >
        {loading ? 'Loading…' : 'View your progress'}
      </button>
    </CoachBubble>
  );
}

export function ChatView() {
  const {
    sessionId,
    results,
    currentTask,
    pendingTask,
    loading,
    initialQuestion,
    advance,
    completeSession,
  } = useAssessmentStore();
  const bottomRef = useRef<HTMLDivElement>(null);

  const [code, setCode] = useState('');
  const [shareState, setShareState] = useState<'idle' | 'copying' | 'copied' | 'error'>('idle');

  const handleShare = async () => {
    if (!sessionId) return;
    setShareState('copying');
    try {
      const share = await apiClient.shareSession(sessionId);
      await navigator.clipboard.writeText(new URL(share.url, window.location.origin).toString());
      setShareState('copied');
    } catch {
      setShareState('error');
    }
  };

  const taskId = currentTask?.id ?? null;
  const phaseIndex = currentTask?.phase_index ?? null;
  useEffect(() => {
    // A phased step carries the candidate's prior code; otherwise start from
    // the scaffold.
    setCode(currentTask?.previous_code ?? currentTask?.scaffold ?? '');
  }, [taskId, phaseIndex, currentTask?.scaffold, currentTask?.previous_code]);

  const handleSubmit = (note: string) => {
    if (!currentTask) return;
    const answer = note ? `${code}${NOTE_SEPARATOR}${note}` : code;
    useAssessmentStore.getState().submitAnswer(currentTask.id, answer);
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [results.length, currentTask?.id, pendingTask?.phase_index, loading]);

  const hasHistory = results.length > 0;
  const showTask = !!currentTask && !pendingTask;
  const finished = !currentTask && results.length > 0 && !loading;

  const last = results[results.length - 1];
  const retryingPhase =
    !!pendingTask &&
    !!last &&
    pendingTask.id === last.task_id &&
    (pendingTask.phase_index ?? 1) === (last.phase_index ?? 1);
  const nextLabel = retryingPhase ? 'Retry step' : 'Next step';

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Single scrollable page: question → parts → editor → composer in one flow */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl space-y-5 px-4 py-6 lg:max-w-4xl xl:max-w-6xl">
          {results.length > 0 && (
            <div className="flex justify-end">
              <button
                onClick={handleShare}
                disabled={loading || shareState === 'copying'}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-3 py-1.5 text-xs text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-accent)]/40 hover:text-[var(--color-accent)] disabled:opacity-40"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
                  <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8M16 6l-4-4-4 4M12 2v13" />
                </svg>
                {shareState === 'copied'
                  ? 'Share link copied'
                  : shareState === 'error'
                    ? 'Share failed'
                    : 'Share trajectory'}
              </button>
            </div>
          )}

          {initialQuestion && !hasHistory && <UserTextBubble text={initialQuestion} />}

          {results.map((r, i) => (
            <Fragment key={`res-${i}`}>
              <QuestionBubble
                prompt={r.prompt}
                parts={r.parts}
                tags={r.tags}
                phaseIndex={r.phase_index}
                phaseTotal={r.phase_total}
              />
              <UserCodeBubble answer={r.userAnswer} language={r.language} />
              <CoachingBubble r={r} />
            </Fragment>
          ))}

          {showTask && currentTask && (
            <QuestionBubble
              prompt={currentTask.prompt}
              parts={currentTask.parts}
              remediation={currentTask.remediation}
              tags={currentTask.tags}
              phaseIndex={currentTask.phase_index}
              phaseTotal={currentTask.phase_total}
            />
          )}

          {showTask && currentTask && (
            <CodeEditor
              key={`${currentTask.id}:${currentTask.phase_index ?? 0}`}
              code={code}
              language={currentTask.language}
              onChange={setCode}
              readOnly={loading}
            />
          )}

          {showTask && currentTask && (
            <div className="space-y-2">
              <Composer
                placeholder="Add a note (optional) and submit…"
                onSubmit={handleSubmit}
                disabled={loading}
                allowEmpty
              />
              {results.length > 0 && (
                <p className="text-center">
                  <button
                    onClick={completeSession}
                    disabled={loading}
                    className="text-xs text-[var(--color-text-muted)] underline-offset-2 transition-colors hover:text-[var(--color-text-secondary)] hover:underline disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    Finish session and view progress
                  </button>
                </p>
              )}
            </div>
          )}

          {/* Teaching pause: hold the next task until the candidate continues. */}
          {pendingTask && (
            <div className="flex justify-center pt-1">
              <button
                onClick={advance}
                disabled={loading}
                className="rounded-lg bg-[var(--color-accent)] px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-40"
              >
                {nextLabel}
              </button>
            </div>
          )}

          {finished && <DoneBubble key="done" />}

          {loading && (
            <CoachBubble>
              <p className="text-[11px] text-[var(--color-text-muted)]">Working…</p>
            </CoachBubble>
          )}

          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
}
