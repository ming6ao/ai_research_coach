import { useEffect, useMemo, useState } from 'react';
import { useAssessmentStore } from '../../stores/assessmentStore';
import { useAuthStore } from '../../stores/authStore';
import { apiClient, type MasteryEntry, type UnifiedSession } from '../../api/client';

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

function masteryTone(mastery: number): string {
  if (mastery >= 0.7) return 'bg-[var(--color-success)]';
  if (mastery >= 0.4) return 'bg-[var(--color-warning)]';
  return 'bg-[var(--color-error)]';
}

function MasteryBar({ value, tone }: { value: number; tone: string }) {
  return (
    <div className="h-2 overflow-hidden rounded-full bg-[var(--color-bg-tertiary)]">
      <div
        className={`h-full rounded-full transition-all duration-700 ${tone}`}
        style={{ width: `${Math.round(value * 100)}%` }}
      />
    </div>
  );
}

function TagChip({ tag, entry, seen }: { tag: string; entry: MasteryEntry; seen: boolean }) {
  const pct = Math.round(entry.score * 100);
  return (
    <span
      title={`${entry.questions_answered} answered`}
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

export function HomeView() {
  const { user } = useAuthStore();
  const { startAssessment, loading, overview, overviewLoading, loadOverview } = useAssessmentStore();
  const [showSessions, setShowSessions] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    loadOverview();
  }, [loadOverview]);

  const handleStartSession = () => {
    if (loading) return;
    startAssessment(undefined, { randomFirst: true });
  };

  const handleStartFamily = (family: string) => {
    if (loading) return;
    startAssessment(undefined, { family });
  };

  const handleOpen = (s: UnifiedSession) => {
    apiClient
      .openSession(s.id)
      .then((res) => {
        useAssessmentStore.getState().resumeSession(res);
      })
      .catch(() => undefined);
  };

  const handleClearAll = async () => {
    if (!window.confirm('Delete ALL sessions and data for this account/browser? This cannot be undone.')) return;
    try {
      await apiClient.clearOwnData();
      loadOverview();
    } catch {
      // Ignore — overview stays as-is.
    }
  };

  const name = user?.display_name || (user ? user.email.split('@')[0] : '');
  const ability = overview?.ability ?? null;
  const mastery = overview?.mastery ?? null;
  const sessions = overview?.sessions ?? [];
  const answered = ability?.questions_answered ?? 0;
  const overallMastery = mastery?.global.score ?? ability?.score ?? null;
  const families = useMemo(() => (mastery ? Object.entries(mastery.families) : []), [mastery]);
  const sortedFamilies = useMemo(
    () => [...families].sort((a, b) => b[1].questions_answered - a[1].questions_answered),
    [families],
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col items-center overflow-y-auto px-4 pb-24">
      <div className="flex w-full max-w-2xl flex-col items-center lg:max-w-4xl xl:max-w-6xl">
        <h1 className="mb-2 text-2xl font-bold text-[var(--color-text-primary)] md:text-3xl">
          {user ? `Welcome back, ${name}!` : 'Practice AI/ML skills'}
        </h1>
        <p className="mb-6 text-sm text-[var(--color-text-secondary)]">
          {user
            ? 'Pick an area or start a mixed session — progress is saved to your account.'
            : 'Pick an area or start a mixed session — progress is saved in this browser.'}
        </p>

        <button
          onClick={handleStartSession}
          disabled={loading}
          className="flex items-center gap-2 rounded-xl bg-[var(--color-accent)] px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
            <path d="M5 3l14 9-14 9V3z" />
          </svg>
          {loading ? 'Starting…' : 'Start practice'}
        </button>
        <p className="mt-2 text-[11px] text-[var(--color-text-muted)]">
          AI Research Coach can make mistakes.
        </p>

        {!overviewLoading && (
          <div className="mt-8 w-full space-y-8">
            <div className="space-y-3">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                Overall mastery
              </h3>
              {overallMastery === null ? (
                <p className="text-sm text-[var(--color-text-muted)]">
                  No questions answered yet. Pick an area below or start a mixed session.
                </p>
              ) : (
                <div className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-4">
                  <div className="mb-2 flex items-end justify-between gap-2">
                    <span className="text-3xl font-bold leading-none text-[var(--color-text-primary)]">
                      {Math.round(overallMastery * 100)}%
                    </span>
                    <span className="text-xs text-[var(--color-text-muted)]">
                      {answered} question{answered === 1 ? '' : 's'} answered
                    </span>
                  </div>
                  <MasteryBar value={overallMastery} tone={masteryTone(overallMastery)} />
                </div>
              )}
            </div>

            {mastery && sortedFamilies.length > 0 && (
              <div className="space-y-3">
                <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                  Mastery by area
                </h3>
                <p className="text-xs text-[var(--color-text-muted)]">
                  Click an area to practice a question from it.
                </p>
                <div className="grid gap-3 md:grid-cols-2">
                  {sortedFamilies.map(([fam, entry]) => {
                    const label = FAMILY_LABELS[fam] ?? fam;
                    const pct = Math.round(entry.score * 100);
                    const famTags = Object.entries(mastery.tags)
                      .filter(([, te]) => te.family === fam)
                      .sort((a, b) => b[1].questions_answered - a[1].questions_answered);
                    return (
                      <div
                        key={fam}
                        className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-4"
                      >
                        <div className="flex w-full items-center justify-between gap-2">
                          <button
                            onClick={() => handleStartFamily(fam)}
                            disabled={loading}
                            title={`Practice ${label}`}
                            className="min-w-0 flex-1 rounded-md text-left transition-colors hover:text-[var(--color-accent)] disabled:opacity-40"
                          >
                            <span className="block truncate text-sm font-semibold text-[var(--color-text-primary)]">
                              {label}
                            </span>
                          </button>
                          <span className="shrink-0 text-sm font-bold text-[var(--color-text-primary)]">
                            {pct}%
                          </span>
                        </div>
                        <div className="mt-2">
                          <MasteryBar value={entry.score} tone={masteryTone(entry.score)} />
                        </div>
                        <div className="mt-1 flex items-center justify-between">
                          <span className="text-[10px] text-[var(--color-text-muted)]">
                            {entry.questions_answered} asked
                          </span>
                          <button
                            onClick={() => setExpanded((e) => ({ ...e, [fam]: !e[fam] }))}
                            className="flex items-center gap-1 text-[10px] text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text-secondary)]"
                          >
                            {expanded[fam] ? 'Hide' : 'Details'}
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
                          </button>
                        </div>
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

            {sessions.length > 0 && (
              <div className="w-full">
                <button
                  onClick={() => setShowSessions((s) => !s)}
                  className="flex w-full items-center justify-between rounded-xl px-2 py-2 text-sm text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text-secondary)]"
                >
                  <span>Recent sessions</span>
                  <svg
                    viewBox="0 0 20 20"
                    fill="currentColor"
                    className={`h-4 w-4 transition-transform ${showSessions ? 'rotate-180' : ''}`}
                  >
                    <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
                  </svg>
                </button>
                {showSessions && (
                  <div className="mt-1 space-y-1">
                    {sessions.map((s) => (
                      <button
                        key={s.id}
                        onClick={() => handleOpen(s)}
                        disabled={loading}
                        className="flex w-full items-center gap-2 rounded-xl border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-3 py-2 text-left text-sm text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-accent)]/40 disabled:opacity-40"
                      >
                        <span
                          className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                            s.done
                              ? 'bg-[var(--color-success)]/15 text-[var(--color-success)]'
                              : 'bg-[var(--color-accent)]/15 text-[var(--color-accent)]'
                          }`}
                        >
                          {s.done ? 'DONE' : 'IN PROGRESS'}
                        </span>
                        <span className="min-w-0 flex-1 truncate">
                          {new Date(s.updated_at).toLocaleString()}
                        </span>
                      </button>
                    ))}
                    <button
                      onClick={handleClearAll}
                      className="w-full px-2 pt-1 text-left text-[11px] text-[var(--color-text-muted)] hover:text-[var(--color-error)]"
                    >
                      Clear all my data
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
