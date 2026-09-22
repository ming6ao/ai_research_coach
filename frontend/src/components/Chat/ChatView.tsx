import { Fragment, memo, useEffect, useRef, useState } from 'react';
import { useAssessmentStore, type ResultWithFeedback } from '../../stores/assessmentStore';
import { CodeEditor } from '../TaskPanel/CodeEditor';
import { Markdown } from '../Markdown/Markdown';
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
      <CodeEditor code={code} language={language} readOnly fitContent />
      {note && <UserTextBubble text={note} />}
    </div>
  );
}

/** Human label for the active step (or a part in a legacy multi-part result). */
function stepLabel(r: ResultWithFeedback, index: number, total: number): string {
  if (total > 1) return `Part ${index + 1}`;
  return r.phase_index != null ? `Step ${r.phase_index}` : 'Result';
}

function scoreTone(pct: number): string {
  return pct >= 80
    ? 'text-[var(--color-success)]'
    : pct <= 40
      ? 'text-[var(--color-error)]'
      : 'text-[var(--color-warning)]';
}

/**
 * The single actionable explanation for the scored step: the judge's
 * `feedback`, which names the gap and says how to fix it. Legacy payloads that
 * lack it fall back to the top-level `feedback` alias.
 */
function coachingText(r: ResultWithFeedback): string {
  return (r.coach?.feedback || r.feedback || '').trim();
}

/** Per-part outcomes for a legacy multi-part result (one active part now). */
function PartResults({ r }: { r: ResultWithFeedback }) {
  const parts = r.result.parts;
  if (!parts || parts.length === 0) return null;
  return (
    <ul className="space-y-1.5">
      {parts.map((p, i) => {
        const part = r.parts?.find((x) => x.key === p.key);
        const max = part?.max_score ?? 5;
        const pct = max ? Math.round((p.score / max) * 100) : 0;
        return (
          <li
            key={p.key}
            className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-2.5 py-1.5"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="min-w-0 truncate text-[13px] text-[var(--color-text-primary)]">
                {stepLabel(r, i, parts.length)}
              </span>
              <span className={`shrink-0 text-[12px] font-semibold ${scoreTone(pct)}`}>
                {p.score}/{max} · {pct}%
              </span>
            </div>
            {p.rationale && (
              <p className="mt-0.5 text-[13px] leading-5 text-[var(--color-text-muted)]">{p.rationale}</p>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function SectionLabel({ children }: { children: string }) {
  return (
    <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
      {children}
    </p>
  );
}

/** Collapsed-by-default reveal of the complete step solution. */
function SolutionReveal({ code }: { code: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-3 py-1.5 text-[13px] font-semibold text-[var(--color-text-primary)] transition-colors hover:bg-[var(--color-bg-tertiary)]"
      >
        {open ? 'Hide complete solution' : 'Show complete solution'}
      </button>
      {open && <CodeBlock code={code} />}
    </div>
  );
}

function CoachingBubble({ r }: { r: ResultWithFeedback }) {
  const coach = r.coach;
  const verdict = verdictFor(r);
  const parts = r.result.parts ?? [];
  const gap = coachingText(r);
  const solution = (coach?.solution || '').trim();
  const max = r.result.max_score;
  const pct = max ? Math.round((r.result.score / max) * 100) : 0;
  const correct = Boolean(max) && r.result.score / max >= 0.8;
  // Only reveal the full answer once the candidate has missed something.
  const showSolution = Boolean(solution) && !correct;
  return (
    <CoachBubble wide>
      <div className="space-y-3">
        {parts.length > 1 ? (
          <PartResults r={r} />
        ) : (
          <div className="flex items-center justify-between gap-3">
            <p className="text-[15px] font-semibold text-[var(--color-text-primary)]">
              {stepLabel(r, 0, 1)}
            </p>
            <span className="flex shrink-0 items-center gap-2">
              {verdict && (
                <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${verdict.cls}`}>
                  {verdict.label}
                </span>
              )}
              <span className={`text-[12px] font-semibold ${scoreTone(pct)}`}>
                {r.result.score}/{max} · {pct}%
              </span>
            </span>
          </div>
        )}
        {/* One actionable explanation under the step heading. A legacy
            multi-part result shows a rationale per part above instead. */}
        {parts.length <= 1 && gap && <Markdown text={gap} size="md" />}
        {coach && coach.steps.length > 0 && (
          <div className="space-y-3">
            <SectionLabel>How to fix it</SectionLabel>
            <ol className="space-y-3">
              {coach.steps.map((step, i) => (
                <li key={i} className="space-y-1.5">
                  <p className="text-[15px] font-semibold text-[var(--color-text-primary)]">
                    {i + 1}. {step.title}
                  </p>
                  {step.explanation && <Markdown text={step.explanation} size="md" />}
                  {step.code && <CodeBlock code={step.code} />}
                </li>
              ))}
            </ol>
          </div>
        )}
        {showSolution && (
          <div className="space-y-2">
            <SectionLabel>Complete solution</SectionLabel>
            <SolutionReveal code={solution} />
          </div>
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

function ChatViewInner() {
  const {
    results,
    currentTask,
    pendingTask,
    loading,
    error,
    selectedLanguage,
    setLanguage,
    advance,
    completeSession,
  } = useAssessmentStore();
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const [code, setCode] = useState('');

  const taskId = currentTask?.id ?? null;
  const phaseIndex = currentTask?.phase_index ?? null;
  const language = selectedLanguage ?? currentTask?.language ?? 'python';
  const multiLanguage = (currentTask?.languages?.length ?? 0) > 1;
  // The picker locks once the task has moved past its first step (the server
  // enforces this too, so every answer is in one language).
  const languageLocked = (currentTask?.phase_index ?? 1) > 1;
  useEffect(() => {
    // Each step starts from its own starter code; nothing is carried forward
    // from a prior answer. Fall back to the default scaffold for
    // single-language steps.
    setCode(
      currentTask?.scaffolds?.[language]
        ?? currentTask?.scaffold
        ?? '',
    );
  }, [
    taskId,
    phaseIndex,
    language,
    currentTask?.scaffold,
    currentTask?.scaffolds,
  ]);

  const handleSubmit = () => {
    if (!currentTask) return;
    useAssessmentStore.getState().submitAnswer(currentTask.id, code);
  };

  // A new task/step starts at the top so the question is visible before the
  // (potentially very tall) editor.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 });
  }, [taskId, phaseIndex]);

  // After a submission, bring the coaching into view. Skipped on the first
  // render so an empty session does not jump past the question.
  useEffect(() => {
    if (results.length === 0) return;
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [results.length, loading]);

  const showTask = !!currentTask && !pendingTask;
  const finished = !currentTask && results.length > 0 && !loading;

  // Delivery always advances to the next step, so the continue control has
  // one label (there is no per-step retry).
  const nextLabel = 'Next step';

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Single scrollable page: question → parts → editor in one flow. The
          submit controls live in the pinned footer below. */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl space-y-5 px-4 py-6 lg:max-w-4xl xl:max-w-6xl">
          {results.map((r, i) => (
            <Fragment key={`res-${i}`}>
              <div
                data-selectable
                data-source-kind="question"
                data-task-id={r.task_id}
                data-step-key={r.parts?.[0]?.key}
              >
                <QuestionBubble
                  parts={r.parts}
                  phaseIndex={r.phase_index}
                  phaseTotal={r.phase_total}
                />
              </div>
              <UserCodeBubble answer={r.userAnswer} language={r.language} />
              <div
                data-selectable
                data-source-kind="coaching"
                data-task-id={r.task_id}
                data-step-key={r.parts?.[0]?.key}
              >
                <CoachingBubble r={r} />
              </div>
            </Fragment>
          ))}

          {showTask && currentTask && (
            <div
              data-selectable
              data-source-kind="question"
              data-task-id={currentTask.id}
              data-step-key={currentTask.parts?.[0]?.key}
            >
              <QuestionBubble
                parts={currentTask.parts}
                remediation={currentTask.remediation}
                phaseIndex={currentTask.phase_index}
                phaseTotal={currentTask.phase_total}
              />
            </div>
          )}

          {showTask && currentTask && multiLanguage && (
            <div className="flex items-center gap-2">
              <label
                htmlFor="answer-language"
                className="text-[11px] font-medium text-[var(--color-text-muted)]"
              >
                Language
              </label>
              <select
                id="answer-language"
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                disabled={languageLocked || loading}
                className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] px-2 py-1 text-xs text-[var(--color-text-primary)] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {currentTask.languages!.map((l) => (
                  <option key={l} value={l}>
                    {l === 'cpp' ? 'C++' : l}
                  </option>
                ))}
              </select>
              <span className="text-[10px] text-[var(--color-text-muted)]">
                {languageLocked ? 'locked for this question' : 'stay the same across steps'}
              </span>
            </div>
          )}

          {showTask && currentTask?.starts_from_previous && (
            <p className="rounded-lg border border-[var(--color-accent)]/30 bg-[var(--color-accent)]/5 px-3 py-1.5 text-[11px] text-[var(--color-text-secondary)]">
              This step continues from the previous step's solution — extend it.
            </p>
          )}

          {showTask && currentTask && (
            <CodeEditor
              key={`${currentTask.id}:${currentTask.phase_index ?? 0}:${language}`}
              code={code}
              language={language}
              onChange={setCode}
              readOnly={loading}
              fitContent
            />
          )}

          {finished && <DoneBubble key="done" />}

          {loading && (
            <CoachBubble>
              <p className="text-[11px] text-[var(--color-text-muted)]">Working…</p>
            </CoachBubble>
          )}

          {error && !loading && (
            <CoachBubble>
              <p className="rounded-lg border border-[var(--color-error)]/40 bg-[var(--color-error)]/10 px-3 py-2 text-sm text-[var(--color-error)]">
                {error}
              </p>
            </CoachBubble>
          )}

          <div ref={bottomRef} />
        </div>
      </div>

      {/*
       * Pinned footer: the editor grows to fit long files with no inner scroll,
       * so the submit/continue controls live outside the scroll container and
       * stay reachable however tall the code gets.
       */}
      {((showTask && currentTask) || pendingTask) && (
        <div className="shrink-0 border-t border-[var(--color-border-default)] bg-[var(--color-bg-primary)]">
          <div className="mx-auto max-w-2xl space-y-2 px-4 py-3 lg:max-w-4xl xl:max-w-6xl">
            {showTask && currentTask && (
              <div className="flex items-center justify-end gap-2">
                <button
                  onClick={completeSession}
                  disabled={loading}
                  title="Finish the session and view your progress (the session otherwise keeps going)"
                  className="rounded-lg px-4 py-2 text-sm text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text-secondary)] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Finish
                </button>
                <button
                  onClick={handleSubmit}
                  disabled={loading}
                  className="rounded-lg bg-[var(--color-accent)] px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Submit
                </button>
              </div>
            )}

            {/* Teaching pause: hold the next task until the candidate continues. */}
            {pendingTask && (
              <div className="flex justify-center">
                <button
                  onClick={advance}
                  disabled={loading}
                  className="rounded-lg bg-[var(--color-accent)] px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {nextLabel}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Memoized so the selection popover / explanation panel toggling in
 * `SessionLayout` cannot re-render (and therefore remount) the transcript —
 * which would collapse a live text selection mid-copy.
 */
export const ChatView = memo(ChatViewInner);
