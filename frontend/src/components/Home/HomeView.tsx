import { useEffect, useMemo, useState } from 'react';
import { useAssessmentStore } from '../../stores/assessmentStore';
import { useAuthStore } from '../../stores/authStore';
import { apiClient, type MasteryEntry, type UnifiedSession } from '../../api/client';
import { Composer } from '../Composer/Composer';

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

export function HomeView() {
  const { user } = useAuthStore();
  const { startAssessment, loading, overview, overviewLoading, loadOverview } = useAssessmentStore();
  const [showSessions, setShowSessions] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    loadOverview();
  }, [loadOverview]);

  const handleSend = (text: string) => {
    if (loading) return;
    startAssessment(text);
  };

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
  const confidence = ability?.confidence ?? 0;
  const answered = ability?.questions_answered ?? 0;
  const families = useMemo(() => (mastery ? Object.entries(mastery.families) : []), [mastery]);

  return (
    <div className="flex min-h-0 flex-1 flex-col items-center overflow-y-auto px-4 pb-24">
      <div className="flex w-full max-w-2xl flex-col items-center lg:max-w-4xl xl:max-w-6xl">
        <h1 className="mb-2 text-2xl font-bold text-[var(--color-text-primary)] md:text-3xl">
          {user ? `Welcome back, ${name}!` : 'What would you like to practice?'}
        </h1>
        <p className="mb-8 text-sm text-[var(--color-text-secondary)]">
          {user
            ? 'Ask AI/ML questions or pick a task — sessions are saved to your account.'
            : 'Try AI/ML interview questions — sessions are saved in this browser.'}
        </p>

        <div className="w-full">
          <Composer placeholder="Ask anything about AI, ML, or coding…" onSubmit={handleSend} disabled={loading} />
        </div>

        <div className="mt-3 flex items-center gap-3">
          <button
            onClick={handleStartSession}
            disabled={loading}
            className="flex items-center gap-1.5 rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-3 py-1.5 text-xs text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-accent)]/40 hover:text-[var(--color-accent)] disabled:opacity-40"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
              <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
            </svg>
            Start a new session
          </button>
          <p className="text-[11px] text-[var(--color-text-muted)]">
            AI Research Coach can make mistakes.
          </p>
        </div>

        {!overviewLoading && (
          <div className="mt-8 w-full space-y-8">
            <div className="space-y-3">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                Overall confidence
              </h3>
              {!ability && (
                <p className="text-sm text-[var(--color-text-muted)]">
                  No questions answered yet. Pick an area below, start a session, or ask your own question.
                </p>
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
                <p className="text-xs text-[var(--color-text-muted)]">
                  Click an area to start a session with a question in that area.
                </p>
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
                        <div className="flex w-full items-center justify-between gap-2">
                          <button
                            onClick={() => handleStartFamily(fam)}
                            disabled={loading}
                            title={`Start a session in ${label}`}
                            className="min-w-0 flex-1 rounded-md text-left transition-colors hover:text-[var(--color-accent)] disabled:opacity-40"
                          >
                            <span className="text-sm font-semibold text-[var(--color-text-primary)] hover:text-[var(--color-accent)]">
                              {label}
                            </span>
                          </button>
                          <button
                            onClick={() => setExpanded((e) => ({ ...e, [fam]: !e[fam] }))}
                            className="flex shrink-0 items-center gap-2 text-xs text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text-secondary)]"
                          >
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
                          </button>
                        </div>
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