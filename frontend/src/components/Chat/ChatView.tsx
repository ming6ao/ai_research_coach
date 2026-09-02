import { Fragment, useEffect, useRef, useState } from 'react';
import { useAssessmentStore, type ResultWithFeedback } from '../../stores/assessmentStore';
import type { Task } from '../../api/client';
import { CodeEditor } from '../TaskPanel/CodeEditor';
import { HintSection } from '../TaskPanel/HintSection';
import { Markdown } from '../Markdown/Markdown';
import { Composer } from '../Composer/Composer';
import { CodeBlock } from '../CodeBlock/CodeBlock';

const NOTE_SEPARATOR = '\n\n---\n';

function splitNote(answer: string): { code: string; note: string } {
  const idx = answer.indexOf(NOTE_SEPARATOR);
  if (idx === -1) return { code: answer, note: '' };
  return { code: answer.slice(0, idx), note: answer.slice(idx + NOTE_SEPARATOR.length).trim() };
}

function CoachBubble({ children, wide }: { children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="flex items-start gap-3">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--color-accent)] text-[10px] font-bold text-white">
        RC
      </div>
      <div className={`min-w-0 flex-1 ${wide ? '' : 'max-w-[85%]'} text-sm leading-6 text-[var(--color-text-primary)]`}>
        {children}
      </div>
    </div>
  );
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

function UserCodeBubble({ answer }: { answer: string }) {
  const { code, note } = splitNote(answer);
  return (
    <div className="space-y-2">
      <CodeEditor code={code} readOnly />
      {note && <UserTextBubble text={note} />}
    </div>
  );
}

function CoachingBubble({ r }: { r: ResultWithFeedback }) {
  const coach = r.coach;
  return (
    <CoachBubble wide>
      <div className="space-y-3">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          {r.scored ? `${r.result.score}/${r.result.max_score} · ${r.result.skill}` : 'Feedback · not scored'}
        </p>
        {coach && (coach.misconception || coach.steps.length > 0) ? (
          <>
            {coach.feedback && <Markdown text={coach.feedback} />}
            {coach.misconception && (
              <div className="rounded-lg border border-[var(--color-warning)]/30 bg-[var(--color-warning)]/5 p-3">
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-warning)]">
                  Where the gap is
                </p>
                <Markdown text={coach.misconception} />
              </div>
            )}
            {coach.steps.length > 0 && (
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
            )}
          </>
        ) : (
          <Markdown text={r.feedback} />
        )}
      </div>
    </CoachBubble>
  );
}

function TaskPromptBubble({ prompt, skill, remediation }: { prompt: string; skill: string; remediation?: Task['remediation'] }) {
  return (
    <CoachBubble>
      <div className="space-y-1">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Question · {skill}
        </p>
        {remediation && (
          <p className="inline-flex items-center gap-1 rounded-full border border-[var(--color-accent)]/40 bg-[var(--color-accent)]/10 px-2.5 py-0.5 text-[11px] font-semibold text-[var(--color-accent)]">
            Warm-up{remediation.node_slug ? ` · focus: ${remediation.node_slug}` : ''}
          </p>
        )}
        <Markdown text={prompt} />
      </div>
    </CoachBubble>
  );
}

function DoneBubble() {
  const { loadReport, loading, mode } = useAssessmentStore();
  const isPractice = mode === 'practice';
  return (
    <CoachBubble>
      <p className="mb-3 text-sm text-[var(--color-text-primary)]">
        {isPractice
          ? "You've browsed all the questions. Nice work!"
          : "You've completed all the questions. Ready to see your results?"}
      </p>
      {isPractice ? (
        <p className="text-xs text-[var(--color-text-muted)]">
          Sign in to save your progress and get a scored report.
        </p>
      ) : (
        <button
          onClick={loadReport}
          disabled={loading}
          className="rounded-lg bg-[var(--color-accent)] px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {loading ? 'Generating…' : 'View Report'}
        </button>
      )}
    </CoachBubble>
  );
}

export function ChatView() {
  const { results, currentTask, mode, loading, initialQuestion } =
    useAssessmentStore();
  const bottomRef = useRef<HTMLDivElement>(null);

  const [code, setCode] = useState('');
  const [viewed, setViewed] = useState<Set<string>>(new Set());
  const [submittedTaskId, setSubmittedTaskId] = useState<string | null>(null);
  const lastTaskId = useRef<string | null>(null);

  if (lastTaskId.current !== currentTask?.id) {
    lastTaskId.current = currentTask?.id ?? null;
    setCode(currentTask?.scaffold ?? '');
    setViewed(new Set((currentTask?.hints ?? []).filter((h) => h.pre_revealed).map((h) => h.id)));
    setSubmittedTaskId(null);
  }

  const revealHint = (id: string) => {
    setViewed((prev) => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });
  };

  const handleSubmit = (note: string) => {
    if (!currentTask) return;
    setSubmittedTaskId(currentTask.id);
    const answer = note ? `${code}${NOTE_SEPARATOR}${note}` : code;
    useAssessmentStore.getState().submitAnswer(currentTask.id, answer, Array.from(viewed));
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [results.length, currentTask?.id, loading]);

  const hasHistory = results.length > 0;
  const waiting = submittedTaskId === currentTask?.id;
  const finished = !currentTask && results.length > 0 && !loading;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Single scrollable page: question → hints → editor → composer in one flow */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl space-y-5 px-4 py-6 lg:max-w-4xl xl:max-w-6xl">
          {initialQuestion && !hasHistory && <UserTextBubble text={initialQuestion} />}

          {results.map((r, i) => (
            <Fragment key={`res-${i}`}>
              <TaskPromptBubble prompt={r.prompt} skill={r.skill} />
              <UserCodeBubble answer={r.userAnswer} />
              <CoachingBubble r={r} />
            </Fragment>
          ))}

          {!waiting && currentTask && (
            <TaskPromptBubble prompt={currentTask.prompt} skill={currentTask.skill} remediation={currentTask.remediation} />
          )}

          {!waiting && currentTask && (currentTask.hints?.length ?? 0) > 0 && (
            <HintSection
              hints={currentTask.hints ?? []}
              viewed={viewed}
              onRevealHint={revealHint}
              disabled={loading}
              mode={mode}
            />
          )}

          {!waiting && currentTask && (
            <CodeEditor
              key={`${currentTask.id}-${submittedTaskId === currentTask.id ? 'locked' : 'editable'}`}
              code={code}
              onChange={setCode}
              readOnly={loading}
            />
          )}

          {!waiting && currentTask && (
            <div className="space-y-2">

              <Composer
                placeholder="Add a note (optional) and submit…"
                onSubmit={handleSubmit}
                disabled={loading}
                allowEmpty
              />
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