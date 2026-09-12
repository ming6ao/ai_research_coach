import { useAssessmentStore } from '../../stores/assessmentStore';

const skillLabels: Record<string, string> = {
  ml_modeling: 'Machine Learning & Modeling',
  ml_systems: 'ML Systems & Infrastructure',
  general: 'General',
};

function humanizeSkill(id: string): string {
  return skillLabels[id] ?? id.replace(/_/g, ' ');
}

function ConfidenceBar({ value, tone }: { value: number; tone: string }) {
  return (
    <div className="mb-1.5 h-2 overflow-hidden rounded-full bg-[var(--color-bg-tertiary)]">
      <div
        className={`h-full rounded-full transition-all duration-700 ${tone}`}
        style={{ width: `${Math.round(value * 100)}%` }}
      />
    </div>
  );
}

export function LearnerProgressView() {
  const { skillStates, results, reset } = useAssessmentStore();

  const skills = Object.entries(skillStates).sort((a, b) => b[1].confidence - a[1].confidence);

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-2xl space-y-8 lg:max-w-4xl xl:max-w-6xl">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-[var(--color-text-primary)]">Your progress</h2>
            <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
              Confidence by skill, based on your answers in this session.
            </p>
          </div>
          <button
            onClick={reset}
            className="rounded-lg bg-[var(--color-accent)] px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)]"
          >
            Start a new session
          </button>
        </div>

        <div className="space-y-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
            Skill confidence
          </h3>
          {skills.length === 0 && (
            <p className="text-sm text-[var(--color-text-muted)]">No skills measured yet.</p>
          )}
          {skills.map(([id, s]) => (
            <div
              key={id}
              className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-4"
            >
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-semibold text-[var(--color-text-primary)]">
                  {humanizeSkill(id)}
                </span>
                <span className="text-xs text-[var(--color-text-muted)]">
                  {s.questions_answered} questions · confidence {(s.confidence * 100).toFixed(0)}%
                </span>
              </div>
              <ConfidenceBar
                value={s.confidence}
                tone={
                  s.confidence >= 0.7
                    ? 'bg-[var(--color-success)]'
                    : s.confidence >= 0.4
                      ? 'bg-[var(--color-warning)]'
                      : 'bg-[var(--color-error)]'
                }
              />
            </div>
          ))}
        </div>

        {results.length > 0 && (
          <div className="space-y-3">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
              Questions answered ({results.length})
            </h3>
            {results.map((r) => (
              <div
                key={r.task_id}
                className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-4"
              >
                <p className="text-sm font-semibold text-[var(--color-text-primary)]">
                  {r.skill} · {r.result.score}/{r.result.max_score}
                </p>
                <p className="mt-1 line-clamp-2 text-xs text-[var(--color-text-secondary)]">{r.prompt}</p>
                {r.coach?.misconception && (
                  <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                    Gap: {r.coach.misconception}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
