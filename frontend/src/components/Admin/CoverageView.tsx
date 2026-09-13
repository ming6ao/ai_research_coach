import { useEffect, useState } from 'react';
import { apiClient, type AdminCoverageReport } from '../../api/client';

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

export function CoverageView({ onError }: { onError: (msg: string) => void }) {
  const [report, setReport] = useState<AdminCoverageReport | null>(null);

  useEffect(() => {
    apiClient
      .adminCoverage()
      .then(setReport)
      .catch((e) => onError(e instanceof Error ? e.message : String(e)));
  }, [onError]);

  if (!report) {
    return <p className="py-8 text-center text-xs text-[var(--color-text-muted)]">Loading coverage…</p>;
  }

  return (
    <div className="min-h-0 flex-1 overflow-auto px-4 pb-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Seed bank coverage
        </h3>
        <p className="text-xs text-[var(--color-text-muted)]">
          Tags with 0 seed tasks are unfilled gaps.
        </p>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        {Object.entries(report.families).map(([fam, info]) => {
          const famTags = Object.entries(report.tags)
            .filter(([, t]) => t.family === fam)
            .sort((a, b) => a[0].localeCompare(b[0]));
          const gapCount = famTags.filter(([, t]) => t.seed_tasks.length === 0).length;
          return (
            <div
              key={fam}
              className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-4"
            >
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-semibold text-[var(--color-text-primary)]">
                  {FAMILY_LABELS[fam] ?? fam}
                </span>
                <span className="text-xs text-[var(--color-text-muted)]">
                  {info.seed_tasks.length} seeds · {info.asked_total} asked
                  {gapCount > 0 ? ` · ${gapCount} gap${gapCount === 1 ? '' : 's'}` : ''}
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {famTags.map(([tag, t]) => {
                  const covered = t.seed_tasks.length > 0;
                  return (
                    <span
                      key={tag}
                      title={
                        covered
                          ? `${tag}: ${t.seed_tasks.length} seed task(s), ${t.asked_total} asked`
                          : `${tag}: UNCOVERED — run --fill-gaps`
                      }
                      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] ${
                        covered
                          ? 'border-[var(--color-accent)]/30 bg-[var(--color-accent)]/5 text-[var(--color-text-secondary)]'
                          : 'border-[var(--color-error)]/50 bg-[var(--color-error)]/10 text-[var(--color-error)]'
                      }`}
                    >
                      {tag}
                      {covered ? ` (${t.seed_tasks.length})` : ' · gap'}
                    </span>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}