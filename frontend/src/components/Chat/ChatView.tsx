import { Fragment, useEffect, useRef, useState } from 'react';
import { useAssessmentStore, type ResultWithFeedback } from '../../stores/assessmentStore';
import { apiClient, type Task } from '../../api/client';
import { CodeEditor } from '../TaskPanel/CodeEditor';
import { Markdown } from '../Markdown/Markdown';
import { Composer } from '../Composer/Composer';
import { CodeBlock } from '../CodeBlock/CodeBlock';

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

function shortGapText(coach: ResultWithFeedback['coach']): string {
  const raw = (coach?.feedback || coach?.misconception || '').trim();
  if (!raw) return '';
  const first = raw.match(/^.*?[.!?](\s|$)/)?.[0]?.trim() ?? raw;
  const singleLine = first.replace(/\s+/g, ' ');
  return singleLine.length > 120 ? `${singleLine.slice(0, 117).trimEnd()}…` : singleLine;
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

function followUpLabel(remediation?: Task['remediation']): string | null {
  if (!remediation) return null;
  switch (remediation.kind) {
    case 'escalation':
      return 'Harder follow-up';
    case 'pivot':
      return 'Related follow-up';
    case 'challenge':
      return 'Fresh challenge';
    default:
      return 'Follow-up';
  }
}

function TagChips({ tags }: { tags?: Task['tags'] }) {
  if (!tags || (!tags.primary && (tags.secondary ?? []).length === 0)) return null;
  const all = [tags.primary, ...(tags.secondary ?? [])].filter(Boolean);
  return (
    <span className="mt-1 flex flex-wrap gap-1">
      {all.map((t) => (
        <span
          key={t}
          className="inline-flex items-center rounded-full border border-[var(--color-accent)]/30 bg-[var(--color-accent)]/5 px-2 py-0.5 text-[10px] text-[var(--color-text-muted)]"
        >
          {t}
        </span>
      ))}
    </span>
  );
}

function TaskPromptBubble({ prompt, parts, remediation, tags }: { prompt: string; parts?: Task['parts']; remediation?: Task['remediation']; tags?: Task['tags'] }) {
  const label = followUpLabel(remediation);
  return (
    <CoachBubble>
      <div className="space-y-1">
        <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Question
          {label && (
            <span className="inline-flex items-center gap-1 rounded-full border border-[var(--color-accent)]/40 bg-[var(--color-accent)]/10 px-2.5 py-0.5 text-[11px] font-semibold normal-case tracking-normal text-[var(--color-accent)]">
              {label}
            </span>
          )}
        </p>
        <Markdown text={prompt} size="lg" />
        {parts && parts.length > 0 && (
          <ol className="space-y-1 border-l border-[var(--color-border-default)] pl-3">
            {parts.map((part, i) => (
              <li key={part.key} className="text-[15px] leading-6 text-[var(--color-text-secondary)]">
                <span className="font-semibold text-[var(--color-text-primary)]">{i + 1}. {part.key}</span>
                {' — '}
                {part.prompt}
              </li>
            ))}
          </ol>
        )}
        <TagChips tags={tags} />
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
  const { sessionId, results, currentTask, loading, initialQuestion, completeSession } =
    useAssessmentStore();
  const bottomRef = useRef<HTMLDivElement>(null);

  const [code, setCode] = useState('');
  const [submittedTaskId, setSubmittedTaskId] = useState<string | null>(null);
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
  useEffect(() => {
    // A version successor carries its predecessor's code to build on.
    setCode(currentTask?.previous_code ?? currentTask?.scaffold ?? '');
    setSubmittedTaskId(null);
  }, [taskId, currentTask?.scaffold, currentTask?.previous_code]);

  const handleSubmit = (note: string) => {
    if (!currentTask) return;
    setSubmittedTaskId(currentTask.id);
    const answer = note ? `${code}${NOTE_SEPARATOR}${note}` : code;
    useAssessmentStore.getState().submitAnswer(currentTask.id, answer);
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [results.length, currentTask?.id, loading]);

  const hasHistory = results.length > 0;
  const waiting = submittedTaskId === currentTask?.id;
  const finished = !currentTask && results.length > 0 && !loading;

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
              <TaskPromptBubble prompt={r.prompt} parts={r.parts} tags={r.tags} />
              <UserCodeBubble answer={r.userAnswer} />
              <CoachingBubble r={r} />
            </Fragment>
          ))}

          {!waiting && currentTask && (
            <TaskPromptBubble prompt={currentTask.prompt} parts={currentTask.parts} remediation={currentTask.remediation} tags={currentTask.tags} />
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