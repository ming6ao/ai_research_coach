import { useAssessmentStore } from '../../stores/assessmentStore';

const skillLabels: Record<string, string> = {
  ml_fundamentals: 'ML Fundamentals',
  deep_learning: 'Deep Learning',
  math_stats: 'Math & Stats',
  experimentation: 'Experimentation',
  coding: 'Programming & Implementation',
  systems: 'Systems',
  mlops: 'MLOps',
  cloud: 'Cloud',
  data_eng: 'Data Engineering',
};

export function ReportView() {
  const { report } = useAssessmentStore();

  if (!report) return null;

  const verdictColor =
    report.verdict === 'Ready'
      ? 'text-[var(--color-success)]'
      : report.verdict.startsWith('Conditionally')
        ? 'text-[var(--color-warning)]'
        : 'text-[var(--color-error)]';

  const skills = Object.entries(report.skill_breakdown).sort(
    (a, b) => b[1].importance - a[1].importance
  );

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-2xl space-y-8">
        <div className="text-center">
          <h2 className="mb-2 text-2xl font-bold text-[var(--color-text-primary)]">
            Assessment Report
          </h2>
          <p className="text-sm text-[var(--color-text-secondary)]">
            {report.candidate} &middot; {report.title}
          </p>
        </div>

        <div className="rounded-xl border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-6 text-center">
          <p className="mb-1 text-sm text-[var(--color-text-muted)]">
            Overall Score
          </p>
          <p className="mb-3 text-5xl font-bold text-[var(--color-text-primary)]">
            {(report.overall_score * 100).toFixed(0)}%
          </p>
          <p className={`text-lg font-semibold ${verdictColor}`}>
            {report.verdict}
          </p>
          <p className="mt-2 text-xs text-[var(--color-text-muted)]">
            {report.questions_answered} questions answered
          </p>
        </div>

        <div className="space-y-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
            Skill Breakdown
          </h3>
          {skills.map(([id, skill]) => (
            <div
              key={id}
              className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-4"
            >
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-semibold text-[var(--color-text-primary)]">
                  {skillLabels[id] ?? id}
                </span>
                <span className="text-xs text-[var(--color-text-muted)]">
                  {skill.questions_answered} questions
                </span>
              </div>
              <div className="mb-2 h-2 overflow-hidden rounded-full bg-[var(--color-bg-tertiary)]">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${
                    skill.score >= 0.8
                      ? 'bg-[var(--color-success)]'
                      : skill.score >= 0.5
                        ? 'bg-[var(--color-warning)]'
                        : 'bg-[var(--color-error)]'
                  }`}
                  style={{ width: `${skill.score * 100}%` }}
                />
              </div>
              <div className="flex justify-between text-xs text-[var(--color-text-muted)]">
                <span>Score: {(skill.score * 100).toFixed(0)}%</span>
                <span>Confidence: {(skill.confidence * 100).toFixed(0)}%</span>
              </div>
              {skill.evidence.length > 0 && (
                <div className="mt-3 space-y-1">
                  {skill.evidence.map((ev, i) => (
                    <div
                      key={i}
                      className="rounded bg-[var(--color-bg-tertiary)] px-3 py-2 text-xs text-[var(--color-text-secondary)]"
                    >
                      {ev}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>

        {report.gaps.length > 0 && (
          <div className="rounded-lg border border-[var(--color-warning)]/30 bg-[var(--color-warning)]/5 p-4">
            <h3 className="mb-2 text-sm font-semibold text-[var(--color-warning)]">
              Areas for Improvement
            </h3>
            <ul className="space-y-1">
              {report.gaps.map((g) => (
                <li key={g} className="text-sm text-[var(--color-text-secondary)]">
                  &bull; {skillLabels[g] ?? g}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
