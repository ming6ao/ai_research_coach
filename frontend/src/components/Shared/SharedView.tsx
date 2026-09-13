import { useEffect, useState } from 'react';
import { apiClient, type FeedbackEntry, type SharedTrajectory } from '../../api/client';
import { Markdown } from '../Markdown/Markdown';
import { useAssessmentStore } from '../../stores/assessmentStore';

function verdictFor(entry: FeedbackEntry): { label: string; cls: string } | null {
  const max = entry.result.max_score;
  if (!max) return null;
  const fraction = entry.result.score / max;
  if (fraction >= 0.8) return { label: 'Correct', cls: 'bg-[var(--color-success)]/15 text-[var(--color-success)]' };
  if (fraction <= 0.4) return { label: 'Incorrect', cls: 'bg-[var(--color-error)]/15 text-[var(--color-error)]' };
  return { label: 'Partially correct', cls: 'bg-[var(--color-warning)]/15 text-[var(--color-warning)]' };
}

function Bubble({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--color-accent)] text-[10px] font-bold text-white">
        RC
      </div>
      <div className="min-w-0 flex-1 text-sm leading-6 text-[var(--color-text-primary)]">
        {children}
      </div>
    </div>
  );
}

function StepBlock({ entry }: { entry: FeedbackEntry }) {
  const verdict = verdictFor(entry);
  const coach = entry.coach;
  return (
    <div className="space-y-4">
      <Bubble>
        <div className="space-y-1">
          <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
            Question
          </p>
          <Markdown text={entry.prompt} />
        </div>
      </Bubble>
      <Bubble>
        <div className="space-y-2">
          <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
            {verdict && (
              <span className={`rounded-full px-2 py-0.5 text-[10px] ${verdict.cls}`}>{verdict.label}</span>
            )}
            <span className="text-[10px] font-normal normal-case">{entry.result.score}/{entry.result.max_score}</span>
          </p>
          {coach && coach.steps.length > 0 ? (
            <ol className="space-y-3">
              {coach.steps.map((step, i) => (
                <li key={i} className="space-y-1.5">
                  <p className="text-sm font-semibold text-[var(--color-text-primary)]">
                    {i + 1}. {step.title}
                  </p>
                  {step.explanation && <Markdown text={step.explanation} />}
                </li>
              ))}
            </ol>
          ) : (
            <Markdown text={entry.feedback} />
          )}
        </div>
      </Bubble>
    </div>
  );
}

export function SharedView({
  token,
  onResumed,
}: {
  token: string;
  onResumed: () => void;
}) {
  const [data, setData] = useState<SharedTrajectory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resuming, setResuming] = useState(false);
  const resumeSession = useAssessmentStore((s) => s.resumeSession);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .openShared(token)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const handleResume = async () => {
    setResuming(true);
    try {
      const res = await apiClient.resumeShared(token);
      resumeSession(res);
      window.history.replaceState({}, '', '/');
      onResumed();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setResuming(false);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="mx-auto w-full max-w-2xl px-4 py-6 lg:max-w-4xl xl:max-w-6xl">
        <div className="mb-6 space-y-2">
          <h1 className="text-xl font-bold text-[var(--color-text-primary)]">
            Shared trajectory
          </h1>
          <p className="text-sm text-[var(--color-text-secondary)]">
            A coaching session shared by another learner — {data ? data.step_index : '…'} step(s).
            {data && data.step_index === 0 && ' The sharer has not completed any steps yet.'}
          </p>
        </div>

        {error && (
          <div className="rounded-lg border border-[var(--color-error)]/30 bg-[var(--color-bg-secondary)] px-4 py-3 text-sm text-[var(--color-error)]">
            {error}
          </div>
        )}

        {!data && !error && (
          <p className="text-sm text-[var(--color-text-muted)]">Loading…</p>
        )}

        {data && (
          <div className="space-y-5">
            {data.steps.length === 0 ? (
              <p className="text-sm text-[var(--color-text-muted)]">
                This trajectory has no steps yet.
              </p>
            ) : (
              data.steps.map((entry, i) => <StepBlock key={i} entry={entry} />)
            )}

            <div className="mt-8 flex items-center gap-3">
              <button
                onClick={handleResume}
                disabled={resuming}
                className="rounded-lg bg-[var(--color-accent)] px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-40"
              >
                {resuming ? 'Resuming…' : 'Resume this trajectory'}
              </button>
              <p className="text-xs text-[var(--color-text-muted)]">
                You'll continue from step {data.step_index} in your own session.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}