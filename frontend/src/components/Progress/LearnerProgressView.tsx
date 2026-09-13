import { useMemo, useState } from 'react';
import { useAssessmentStore } from '../../stores/assessmentStore';
import type { MasteryEntry } from '../../api/client';

const FAMILY_LABELS: Record<string, string> = {
  python: 'Python',
  data_etl: 'Data / ETL',
  feature_eng: 'Feature engineering',
  ml_classical: 'Classical ML',
  stats_probability: 'Stats & probability',
  training: 'Training',
  optimization: 'Optimization',
  dl_arch: 'Deep learning architectures',
  llm_genai: 'LLMs & generative AI',
  eval: 'Evaluation',
  mlops_serving: 'MLOps & serving',
};

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

function toneFor(confidence: number): string {
  if (confidence >= 0.7) return 'bg-[var(--color-success)]';
  if (confidence >= 0.4) return 'bg-[var(--color-warning)]';
  return 'bg-[var(--color-error)]';
}

function TagChip({ tag, entry, seen }: { tag: string; entry: MasteryEntry; seen: boolean }) {
  const pct = Math.round(entry.score * 100);
  return (
    <span
      title={`${entry.questions_answered} answered · ${pct}%`}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] ${
        seen
          ? 'border-[var(--color-accent)]/40 bg-[var(--color-accent)]/10 text-[var(--color-accent)]'
          : 'border-[var(--color-border-default)] bg-[var(--color-bg-tertiary)]/60 text-[var(--color-text-muted)]'
      }`}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: `var(--color-${seen ? 'accent' : 'text-muted'})` }} />
      {tag} · {pct}%
    </span>
  );
}

export function LearnerProgressView() {
  const { ability, mastery, results, reset } = useAssessmentStore();

  const confidence = ability?.confidence ?? 0;
  const answered = ability?.questions_answered ?? results.length;

  const families = useMemo(() => (mastery ? Object.entries(mastery.families) : []), [mastery]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-2xl space-y-8 lg:max-w-4xl xl:max-w-6xl">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-[var(--color-text-primary)]">Your progress</h2>
            <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
              Overall confidence plus per-family and per-tag mastery, based on your answers.
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
            Overall confidence
          </h3>
          {!ability && (
            <p className="text-sm text-[var(--color-text-muted)]">No questions answered yet.</p>
          )}
          {ability && (
            <div className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-semibold text-[var(--color-text-primary)]">
                  Overall
                </span>
                <span className="text-xs text-[var(--color-text-muted)]">
                  {answered} questions · confidence {(confidence * 100).toFixed(0)}%
                </span>
              </div>
              <ConfidenceBar value={confidence} tone={toneFor(confidence)} />
            </div>
          )}
        </div>

        {mastery && families.length > 0 && (
          <div className="space-y-3">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
              Mastery by area
            </h3>
            <div className="grid gap-3 md:grid-cols-2">
              {families.map(([fam, entry]) => {
                const label = FAMILY_LABELS[fam] ?? fam;
                const famTags = Object.entries(mastery.tags)
                  .filter(([, te]) => te.family === fam)
                  .sort((a, b) => b[1].questions_answered - a[1].questions_answered);
                return (
                  <div
                    key={fam}
                    className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-4"
                  >
                    <button
                      onClick={() => setExpanded((e) => ({ ...e, [fam]: !e[fam] }))}
                      className="flex w-full items-center justify-between text-left"
                    >
                      <span className="text-sm font-semibold text-[var(--color-text-primary)]">
                        {label}
                      </span>
                      <span className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
                        {entry.questions_answered} asked · {(entry.confidence * 100).toFixed(0)}%
                        <svg
                          viewBox="0 0 20 20"
                          fill="currentColor"
                          className={`h-3 w-3 transition-transform ${expanded[fam] ? 'rotate-180' : ''}`}
                        >
                          <path
                            fillRule="evenodd"
                            d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
                            clipRule="evenodd"
                          />
                        </svg>
                      </span>
                    </button>
                    <ConfidenceBar value={entry.confidence} tone={toneFor(entry.confidence)} />
                    {expanded[fam] && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {famTags.map(([tag, te]) => (
                          <TagChip key={tag} tag={tag} entry={te} seen={te.questions_answered > 0} />
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

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
                  {r.result.score}/{r.result.max_score}
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