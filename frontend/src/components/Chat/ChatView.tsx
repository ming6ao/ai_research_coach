import { Fragment, useEffect, useRef } from 'react';
import { useAssessmentStore } from '../../stores/assessmentStore';
import { useAuthStore } from '../../stores/authStore';
import { CodeTask } from '../TaskPanel/CodeTask';
import { Markdown } from '../Markdown/Markdown';
import { CodeBlock } from '../CodeBlock/CodeBlock';
import type { Task, EvaluationResult } from '../../api/client';

function CoachBubble({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--color-accent)] text-xs font-bold text-white">
        RC
      </div>
      <div className="min-w-0 max-w-[88%] flex-1 rounded-2xl rounded-tl-sm border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-4 py-3">
        {children}
      </div>
    </div>
  );
}

function UserBubble({ code }: { code: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%]">
        <div className="mb-1 text-right text-xs text-[var(--color-text-muted)]">You</div>
        <div className="overflow-hidden rounded-2xl rounded-tr-sm border border-[var(--color-accent)]/40 bg-[var(--color-bg-elevated)] px-3 py-2">
          <CodeBlock code={code} />
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
  result: EvaluationResult;
  feedback: string;
  practice?: boolean;
}) {
  return (
    <CoachBubble>
      <div className="space-y-2">
        {practice ? (
          <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
            Practice feedback &middot; not scored
          </p>
        ) : (
          <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
            Score {result.score}/{result.max_score} &middot; {result.skill}
          </p>
        )}
        <Markdown text={feedback} />
      </div>
    </CoachBubble>
  );
}

function PastTaskBubble({ prompt, skill }: { prompt: string; skill: string }) {
  return (
    <CoachBubble>
      <div className="space-y-1">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Question &middot; {skill}
        </p>
        <Markdown text={prompt} />
      </div>
    </CoachBubble>
  );
}

function TaskCard({ task }: { task: Task }) {
  const { submitAnswer, practiceSubmit, skipTask, endPractice, mode, loading } = useAssessmentStore();
  return (
    <CoachBubble>
      <div className="h-[540px]">
        <CodeTask
          task={task}
          mode={mode}
          onSubmit={submitAnswer}
          onPracticeSubmit={practiceSubmit}
          onSkip={skipTask}
          onEndPractice={endPractice}
          disabled={loading}
        />
      </div>
    </CoachBubble>
  );
}

function DoneBubble() {
  const { loadReport, loading } = useAssessmentStore();
  return (
    <CoachBubble>
      <div className="space-y-3">
        <p className="text-sm text-[var(--color-text-primary)]">
          You&rsquo;ve completed all the questions. Ready to see your results?
        </p>
        <button
          onClick={loadReport}
          disabled={loading}
          className="rounded-lg bg-[var(--color-accent)] px-6 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {loading ? 'Generating...' : 'View Report'}
        </button>
      </div>
    </CoachBubble>
  );
}

function PracticeDoneBubble() {
  const { endPractice } = useAssessmentStore();
  return (
    <CoachBubble>
      <div className="space-y-3">
        <p className="text-sm text-[var(--color-text-primary)]">
          You&rsquo;ve browsed all the practice questions. Nice work!
        </p>
        <button
          onClick={endPractice}
          className="rounded-lg border border-[var(--color-border-default)] px-6 py-2.5 text-sm font-medium text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-border-focus)] hover:text-[var(--color-text-primary)]"
        >
          Back to start
        </button>
      </div>
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
      <div className="space-y-1">
        <p className="text-sm font-semibold text-[var(--color-text-primary)]">
          {isPractice ? 'Welcome, guest!' : `Welcome${name ? `, ${name}` : ''}!`}
        </p>
        <p className="text-xs leading-relaxed text-[var(--color-text-secondary)]">
          {isPractice
            ? "You're in guest practice mode. Try real ML interview questions, request hints, and check your answers — nothing is scored or saved. Log in to run a scored assessment."
            : "I'm your AI Research Coach. I'll ask coding questions one at a time and score your answers as we go."}
        </p>
      </div>
    </CoachBubble>
  );
}

export function ChatView() {
  const { results, practiceFeedback, currentTask, mode, totalTasks, taskIndex, loading } =
    useAssessmentStore();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [results.length, practiceFeedback.length, currentTask?.id, loading]);

  const allDone = totalTasks > 0 && taskIndex >= totalTasks && !currentTask;

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-4 px-4 py-6">
        <WelcomeBubble />

        {results.map((r, i) => (
          <Fragment key={`res-${i}`}>
            <PastTaskBubble prompt={r.prompt} skill={r.skill} />
            <UserBubble code={r.userAnswer} />
            <FeedbackBubble result={r.result} feedback={r.feedback} />
          </Fragment>
        ))}

        {practiceFeedback.map((p, i) => (
          <Fragment key={`practice-${i}`}>
            <UserBubble code={p.answer} />
            <FeedbackBubble result={p.result} feedback={p.feedback} practice />
          </Fragment>
        ))}

        {currentTask && <TaskCard key={currentTask.id} task={currentTask} />}

        {allDone && mode === 'assessment' && <DoneBubble key="done" />}
        {allDone && mode === 'practice' && <PracticeDoneBubble key="p-done" />}

        {loading && (
          <CoachBubble>
            <p className="text-xs text-[var(--color-text-muted)]">Working...</p>
          </CoachBubble>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}