import { Fragment, useEffect, useRef, useState } from 'react';
import { useAssessmentStore } from '../../stores/assessmentStore';
import { useAuthStore } from '../../stores/authStore';
import { CodeTask } from '../TaskPanel/CodeTask';
import { Markdown } from '../Markdown/Markdown';
import { Composer } from '../Composer/Composer';


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

function UserBubble({ code }: { code: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%]">
        <div className="mb-1 text-right text-[11px] text-[var(--color-text-muted)]">You</div>
        <pre className="overflow-x-auto rounded-2xl rounded-tr-sm bg-[var(--color-bg-elevated)] px-4 py-3 text-[13px] leading-5 text-[var(--color-text-primary)]">
          <code>{code}</code>
        </pre>
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

function FeedbackBubble({
  result,
  feedback,
  practice,
}: {
  result: { score: number; max_score: number; skill: string };
  feedback: string;
  practice?: boolean;
}) {
  return (
    <CoachBubble>
      <div className="space-y-1">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          {practice ? 'Feedback · not scored' : `${result.score}/${result.max_score} · ${result.skill}`}
        </p>
        <Markdown text={feedback} />
      </div>
    </CoachBubble>
  );
}

function TaskPromptBubble({ prompt, skill }: { prompt: string; skill: string }) {
  return (
    <CoachBubble>
      <div className="space-y-1">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Question · {skill}
        </p>
        <Markdown text={prompt} />
      </div>
    </CoachBubble>
  );
}

function DoneBubble() {
  const { loadReport, mode, endPractice, loading } = useAssessmentStore();
  const isPractice = mode === 'practice';
  return (
    <CoachBubble>
      <p className="mb-3 text-sm text-[var(--color-text-primary)]">
        {isPractice
          ? "You've browsed all the practice questions. Nice work!"
          : "You've completed all the questions. Ready to see your results?"}
      </p>
      <button
        onClick={isPractice ? endPractice : loadReport}
        disabled={loading}
        className={`rounded-lg px-5 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
          isPractice
            ? 'border border-[var(--color-border-default)] text-[var(--color-text-secondary)] hover:border-[var(--color-border-focus)] hover:text-[var(--color-text-primary)]'
            : 'bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent-hover)]'
        }`}
      >
        {isPractice ? 'Back to start' : loading ? 'Generating…' : 'View Report'}
      </button>
    </CoachBubble>
  );
}

function WelcomeBubble() {
  const { mode } = useAssessmentStore();
  const { user } = useAuthStore();
  const isPractice = mode === 'practice';
  const name = user?.display_name || (user ? user.email.split('@')[0] : '');

  return (
    <CoachBubble>
      <p className="text-sm font-semibold text-[var(--color-text-primary)]">
        {isPractice ? 'Welcome, guest!' : `Welcome${name ? `, ${name}` : ''}!`}
      </p>
      <p className="mt-1 text-[13px] text-[var(--color-text-secondary)]">
        {isPractice
          ? "You're in practice mode — nothing is scored or saved. Answer questions and get feedback."
          : "I'll ask coding questions one at a time and score your answers. Let's begin."}
      </p>
    </CoachBubble>
  );
}

export function ChatView() {
  const { results, currentTask, mode, totalTasks, taskIndex, loading, initialQuestion } =
    useAssessmentStore();
  const bottomRef = useRef<HTMLDivElement>(null);

  const [code, setCode] = useState('');
  const [viewed, setViewed] = useState<Set<string>>(new Set());
  const lastTaskId = useRef<string | null>(null);

  if (lastTaskId.current !== currentTask?.id) {
    lastTaskId.current = currentTask?.id ?? null;
    setCode(currentTask?.scaffold ?? '');
    setViewed(new Set((currentTask?.hints ?? []).filter((h) => h.pre_revealed).map((h) => h.id)));
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
    const answer = note ? `${code}\n\n---\n${note}` : code;
    useAssessmentStore.getState().submitAnswer(currentTask.id, answer, Array.from(viewed));
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [results.length, currentTask?.id, loading]);

  const allDone = totalTasks > 0 && taskIndex >= totalTasks && !currentTask;
  const hasHistory = results.length > 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
      {/* Left pane: conversation */}
      <div className="min-h-0 flex-1 overflow-y-auto border-r border-[var(--color-border-default)]">
        <div className="mx-auto max-w-2xl space-y-5 px-4 py-6">
          {/* Show user's typed question as first message, or welcome bubble */}
          {initialQuestion && !hasHistory ? (
            <UserTextBubble text={initialQuestion} />
          ) : (
            !hasHistory && <WelcomeBubble />
          )}

          {results.map((r, i) => (
            <Fragment key={`res-${i}`}>
              <TaskPromptBubble prompt={r.prompt} skill={r.skill} />
              <UserBubble code={r.userAnswer} />
              <FeedbackBubble result={r.result} feedback={r.feedback} practice={!r.scored} />
            </Fragment>
          ))}

          {/* Show current task prompt only if there's history (not the initial question echo) */}
          {currentTask && hasHistory && <TaskPromptBubble prompt={currentTask.prompt} skill={currentTask.skill} />}

          {allDone && <DoneBubble key="done" />}

          {loading && (
            <CoachBubble>
              <p className="text-[11px] text-[var(--color-text-muted)]">Working…</p>
            </CoachBubble>
          )}

          {currentTask && (
            <div className="space-y-2">
              {mode === 'practice' && (
                <div className="flex justify-end">
                  <button
                    onClick={useAssessmentStore.getState().endPractice}
                    disabled={loading}
                    className="rounded-lg px-2.5 py-1 text-[11px] text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text-secondary)] disabled:opacity-40"
                  >
                    End practice
                  </button>
                </div>
              )}
              <Composer
                placeholder={
                  mode === 'practice'
                    ? 'Check my answer…'
                    : 'Add a note (optional) and submit…'
                }
                onSubmit={handleSubmit}
                disabled={loading || !code.trim()}
              />
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      </div>

      {/* Right pane: active task */}
      <div className="flex w-full flex-col border-t border-[var(--color-border-default)] min-h-[420px] lg:w-[42%] lg:min-h-0 lg:border-t-0">
        {currentTask ? (
          <div className="flex min-h-0 flex-1 flex-col px-3 py-3">
            <CodeTask
              key={currentTask.id}
              task={currentTask}
              mode={mode}
              code={code}
              onChangeCode={setCode}
              viewed={viewed}
              onRevealHint={revealHint}
              disabled={loading}
            />
          </div>
        ) : allDone ? (
          <div className="flex min-h-0 flex-1 items-center justify-center px-6">
            <p className="text-sm text-[var(--color-text-muted)]">
              {mode === 'assessment' ? 'All questions answered.' : 'All questions browsed.'}
            </p>
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 items-center justify-center px-6">
            <p className="text-sm text-[var(--color-text-muted)]">
              {loading ? 'Loading…' : 'Waiting for next task…'}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
