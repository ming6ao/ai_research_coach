import { useEffect, useMemo, useState } from 'react';
import { useAssessmentStore } from '../../stores/assessmentStore';
import { useAuthStore } from '../../stores/authStore';
import { apiClient, type Taxonomy, type MasteryArea, type MasteryEntry, type UnifiedSession } from '../../api/client';

function label(id: string | null | undefined): string {
  if (!id) return '';
  return id
    .split('_')
    .map((w) => (w.length <= 3 && w === w.toLowerCase() ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(' ');
}

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

function SkillChip({ id, entry, onStart }: { id: string; entry: MasteryEntry; onStart: (id: string) => void }) {
  const pct = Math.round(entry.score * 100);
  const seen = entry.questions_answered > 0;
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onStart(id);
      }}
      title={`Practice ${label(id)} · ${entry.questions_answered} answered`}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] transition-colors ${
        seen
          ? 'border-[var(--color-accent)]/40 bg-[var(--color-accent)]/10 text-[var(--color-accent)] hover:bg-[var(--color-accent)]/20'
          : 'border-[var(--color-border-default)] bg-[var(--color-bg-tertiary)]/60 text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]'
      }`}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: `var(--color-${seen ? 'accent' : 'text-muted'})` }} />
      {label(id)} · {pct}%
    </button>
  );
}

const EMPTY_ENTRY: MasteryEntry = { score: 0, confidence: 0, questions_answered: 0 };
const EMPTY_AREA: MasteryArea = { ...EMPTY_ENTRY, skills: {} };

export function HomeView() {
  const { user } = useAuthStore();
  const { startAssessment, loading, overview, overviewLoading, loadOverview } = useAssessmentStore();
  const [showSessions, setShowSessions] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [taxonomy, setTaxonomy] = useState<Taxonomy | null>(null);

  useEffect(() => {
    loadOverview();
  }, [loadOverview]);

  useEffect(() => {
    apiClient
      .taxonomy()
      .then(setTaxonomy)
      .catch(() => undefined);
  }, []);

  const handleStartSession = () => {
    if (loading) return;
    startAssessment(undefined, { randomFirst: true });
  };

  const handleStartNode = (node: string) => {
    if (loading) return;
    startAssessment(undefined, { node });
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

  const domains = useMemo(() => {
    if (taxonomy) {
      return taxonomy.domains.map((domain) => ({
        domain,
        areas: Object.keys(taxonomy.areas).filter((a) => taxonomy.tree[domain]?.[a]),
      }));
    }
    // Fallback before the taxonomy loads: whatever the mastery block reports.
    return Object.entries(mastery?.domains ?? {}).map(([domain, d]) => ({
      domain,
      areas: Object.keys(d.areas ?? {}),
    }));
  }, [taxonomy, mastery]);

  return (
    <div className="flex min-h-0 flex-1 flex-col items-center overflow-y-auto px-4 pb-24">
      <div className="flex w-full max-w-2xl flex-col items-center lg:max-w-4xl xl:max-w-6xl">
        <h1 className="mb-2 text-2xl font-bold text-[var(--color-text-primary)] md:text-3xl">
          {user ? `Welcome back, ${name}!` : 'Practice AI/ML skills'}
        </h1>
        <p className="mb-6 text-sm text-[var(--color-text-secondary)]">
          {user
            ? 'Pick a domain, area, or skill — progress is saved to your account.'
            : 'Pick a domain, area, or skill — progress is saved in this browser.'}
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

            <div className="space-y-6">
              <div className="space-y-1">
                <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                  Mastery by domain
                </h3>
                <p className="text-xs text-[var(--color-text-muted)]">
                  Click a domain, area, or skill to practice a question from it.
                </p>
              </div>
              {domains.map(({ domain, areas }) => {
                const domainEntry: MasteryEntry = mastery?.domains?.[domain] ?? EMPTY_ENTRY;
                const domainStarted = domainEntry.questions_answered > 0;
                return (
                  <div key={domain} className="space-y-3">
                    <button
                      type="button"
                      onClick={() => handleStartNode(domain)}
                      disabled={loading}
                      title={`Practice ${label(domain)}`}
                      className="flex w-full items-center justify-between gap-3 rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-4 py-3 text-left transition-colors hover:border-[var(--color-accent)]/40 disabled:opacity-40"
                    >
                      <span className="text-base font-bold text-[var(--color-text-primary)]">
                        {label(domain)}
                      </span>
                      <span className="flex items-center gap-3">
                        <span className="text-sm font-bold text-[var(--color-text-primary)]">
                          {domainStarted ? `${Math.round(domainEntry.score * 100)}%` : 'New'}
                        </span>
                        <span className="text-[10px] text-[var(--color-text-muted)]">
                          {domainStarted ? `${domainEntry.questions_answered} asked` : ''}
                        </span>
                      </span>
                    </button>
                    <div className="grid gap-3 md:grid-cols-2">
                      {areas.map((area) => {
                        const entry: MasteryArea = mastery?.domains?.[domain]?.areas?.[area] ?? EMPTY_AREA;
                        const started = entry.questions_answered > 0;
                        const skills = taxonomy?.tree?.[domain]?.[area] ?? [];
                        return (
                          <div
                            key={area}
                            className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-4"
                          >
                            <div className="flex w-full items-center justify-between gap-2">
                              <button
                                type="button"
                                onClick={() => handleStartNode(area)}
                                disabled={loading}
                                title={`Practice ${label(area)}`}
                                className="min-w-0 flex-1 rounded-md text-left transition-colors hover:text-[var(--color-accent)] disabled:opacity-40"
                              >
                                <span className="block truncate text-sm font-semibold text-[var(--color-text-primary)]">
                                  {label(area)}
                                </span>
                              </button>
                              <span className="shrink-0 text-sm font-bold text-[var(--color-text-primary)]">
                                {started ? `${Math.round(entry.score * 100)}%` : 'New'}
                              </span>
                            </div>
                            <div className="mt-2">
                              <MasteryBar value={started ? entry.score : 0} tone={masteryTone(entry.score)} />
                            </div>
                            <div className="mt-1 flex items-center justify-between">
                              <span className="text-[10px] text-[var(--color-text-muted)]">
                                {started ? `${entry.questions_answered} asked` : 'Not started'}
                              </span>
                              {skills.length > 0 && (
                                <button
                                  type="button"
                                  onClick={() => setExpanded((e) => ({ ...e, [area]: !e[area] }))}
                                  className="flex items-center gap-1 text-[10px] text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text-secondary)]"
                                >
                                  {expanded[area] ? 'Hide' : 'Skills'}
                                  <svg
                                    viewBox="0 0 20 20"
                                    fill="currentColor"
                                    className={`h-3 w-3 transition-transform ${expanded[area] ? 'rotate-180' : ''}`}
                                  >
                                    <path
                                      fillRule="evenodd"
                                      d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
                                      clipRule="evenodd"
                                    />
                                  </svg>
                                </button>
                              )}
                            </div>
                            {expanded[area] && skills.length > 0 && (
                              <div className="mt-2 flex flex-wrap gap-1.5">
                                {skills.map((skill) => (
                                  <SkillChip
                                    key={skill}
                                    id={skill}
                                    entry={entry.skills?.[skill] ?? EMPTY_ENTRY}
                                    onStart={handleStartNode}
                                  />
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>

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
