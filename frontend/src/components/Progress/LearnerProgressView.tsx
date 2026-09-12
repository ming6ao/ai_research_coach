import { useAssessmentStore } from '../../stores/assessmentStore';

const skillLabels: Record<string, string> = {
  ml_modeling: 'Machine Learning & Modeling',
  ml_systems: 'ML Systems & Infrastructure',
  general: 'General',
};

function confidenceBar(value: number, cls: string) {
  return (
    <div className="mb-1.5 h-2 overflow-hidden rounded-full bg-[var(--color-bg-tertiary)]">
      <div
        className={`h-full rounded-full transition-all duration-700 ${cls}`}
        style={{ width: `${Math.round(value * 100)}%` }}
      />
    </div>
  );
}

function statusColor(status: string): string {
  switch (status) {
    case 'mastered':
      return 'bg-[var(--color-success)]/15 text-[var(--color-success)]';
    case 'proficient':
      return 'bg-[var(--color-accent)]/15 text-[var(--color-accent)]';
    case 'developing':
      return 'bg-[var(--color-warning)]/15 text-[var(--color-warning)]';
    case 'uncertain':
      return 'bg-[var(--color-warning)]/15 text-[var(--color-warning)]';
    default:
      return 'bg-[var(--color-bg-tertiary)] text-[var(--color-text-muted)]';
  }
}

export function LearnerProgressView() {
  const { skillStates, learnerSnapshot, reset } = useAssessmentStore();

  const skills = Object.entries(skillStates).sort((a, b) => b[1].confidence - a[1].confidence);
  const nodes = Object.entries(learnerSnapshot?.states ?? {}).sort(
    (a, b) => b[1].uncertainty - a[1].uncertainty
  );
  const misconceptions = learnerSnapshot?.misconceptions ?? [];
  const nextAction = learnerSnapshot?.next_action ?? null;

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-2xl space-y-8 lg:max-w-4xl xl:max-w-6xl">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-[var(--color-text-primary)]">Your progress</h2>
            <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
              Confidence by skill, plus what the coach thinks you should work on next.
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
                  {skillLabels[id] ?? id}
                </span>
                <span className="text-xs text-[var(--color-text-muted)]">
                  {s.questions_answered} questions · confidence {(s.confidence * 100).toFixed(0)}%
                </span>
              </div>
              {confidenceBar(
                s.confidence,
                s.confidence >= 0.7
                  ? 'bg-[var(--color-success)]'
                  : s.confidence >= 0.4
                    ? 'bg-[var(--color-warning)]'
                    : 'bg-[var(--color-error)]'
              )}
            </div>
          ))}
        </div>

        <div className="space-y-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
            Knowledge nodes
          </h3>
          {nodes.length === 0 && (
            <p className="text-sm text-[var(--color-text-muted)]">No knowledge nodes measured yet.</p>
          )}
          {nodes.map(([nodeId, s]) => (
            <div
              key={nodeId}
              className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-4"
            >
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="min-w-0 truncate text-sm font-semibold text-[var(--color-text-primary)]">
                  {s.name}
                </span>
                <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold ${statusColor(s.status)}`}>
                  {s.status}
                </span>
              </div>
              <div className="flex justify-between text-xs text-[var(--color-text-muted)]">
                <span>Mastery: {(s.mastery * 100).toFixed(0)}%</span>
                <span>Confidence: {((1 - s.uncertainty) * 100).toFixed(0)}%</span>
                <span>{s.evidence_count} observations</span>
              </div>
            </div>
          ))}
        </div>

        {misconceptions.length > 0 && (
          <div className="space-y-3">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-warning)]">
              Misconceptions to clear up
            </h3>
            {misconceptions.map((m) => (
              <div
                key={m.node_id}
                className="rounded-lg border border-[var(--color-warning)]/30 bg-[var(--color-warning)]/5 p-4"
              >
                <p className="text-sm font-semibold text-[var(--color-text-primary)]">
                  {m.name ?? 'Unknown gap'}
                </p>
                <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                  Confidence: {(m.confidence * 100).toFixed(0)}% · {m.status}
                </p>
              </div>
            ))}
          </div>
        )}

        {nextAction && (
          <div className="space-y-3">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
              Suggested next focus
            </h3>
            <div className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-4">
              <p className="text-sm font-semibold text-[var(--color-text-primary)]">
                {nextAction.action_type.replace(/_/g, ' ')}
                {nextAction.name ? ` → ${nextAction.name}` : ''}
              </p>
              {nextAction.rationale && (
                <p className="mt-1 text-xs text-[var(--color-text-secondary)]">{nextAction.rationale}</p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}