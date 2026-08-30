import { useEffect, useState } from 'react';
import { useAssessmentStore } from '../../stores/assessmentStore';
import { useAuthStore } from '../../stores/authStore';
import { apiClient, type UnifiedSession } from '../../api/client';

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

export function WelcomeView() {
  const { user } = useAuthStore();
  const { startAssessment, resumeSession, loading } = useAssessmentStore();
  const [sessions, setSessions] = useState<UnifiedSession[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .listSessions()
      .then((res) => {
        if (!cancelled) setSessions(res.sessions);
      })
      .catch(() => {
        if (!cancelled) setSessions([]);
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!user) return null;
  const name = user.display_name || user.email.split('@')[0];

  const handleOpen = (s: UnifiedSession) => {
    apiClient
      .openSession(s.id, s.status)
      .then((res) => resumeSession(res))
      .catch(() => undefined);
  };

  const handleClearAll = async () => {
    if (!window.confirm('Delete ALL sessions and assessments for your account? This cannot be undone.')) return;
    try {
      await apiClient.clearCandidateData(user.email);
      setSessions([]);
    } catch {
      // Ignore — list stays as-is.
    }
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-4 px-4 py-6">
        <CoachBubble>
          <div className="space-y-4">
            <div className="space-y-1">
              <p className="text-sm font-semibold text-[var(--color-text-primary)]">
                Welcome back, {name}!
              </p>
              <p className="text-xs leading-relaxed text-[var(--color-text-secondary)]">
                Ready for a scored assessment? Your answers, feedback, and reports are saved to
                your account so you can pick up where you left off.
              </p>
            </div>
            <button
              onClick={() => startAssessment(user.email, 'assessment')}
              disabled={loading}
              className="rounded-lg bg-[var(--color-accent)] px-6 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {loading ? 'Starting...' : 'Start a new assessment'}
            </button>
          </div>
        </CoachBubble>

        {loaded && sessions.length > 0 && (
          <CoachBubble>
            <div className="space-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                Your sessions
              </p>
              {sessions.map((s) => (
                <button
                  key={s.id}
                  onClick={() => handleOpen(s)}
                  disabled={loading}
                  className="flex w-full items-center gap-2 rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] px-3 py-2 text-left text-sm text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-accent)]/50"
                >
                  <span
                    className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                      s.status === 'active'
                        ? 'bg-[var(--color-accent)]/15 text-[var(--color-accent)]'
                        : 'bg-[var(--color-success)]/15 text-[var(--color-success)]'
                    }`}
                  >
                    {s.status === 'active' ? 'IN PROGRESS' : 'DONE'}
                  </span>
                  <span className="min-w-0 flex-1 truncate">
                    {s.score != null && `— ${(s.score * 100).toFixed(0)}%`}
                    {' — '}
                    {new Date(s.updated_at).toLocaleString()}
                  </span>
                </button>
              ))}
            </div>
          </CoachBubble>
        )}

        {loaded && sessions.length === 0 && (
          <CoachBubble>
            <p className="text-xs text-[var(--color-text-muted)]">
              No sessions yet — your first scored assessment will show up here.
            </p>
          </CoachBubble>
        )}

        <div className="flex justify-end px-1">
          <button
            onClick={handleClearAll}
            className="text-xs text-[var(--color-text-muted)] underline-offset-2 hover:text-[var(--color-error)] hover:underline"
          >
            Clear all my data
          </button>
        </div>
      </div>
    </div>
  );
}