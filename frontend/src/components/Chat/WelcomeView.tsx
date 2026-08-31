import { useEffect, useState } from 'react';
import { useAssessmentStore } from '../../stores/assessmentStore';
import { useAuthStore } from '../../stores/authStore';
import { apiClient, type UnifiedSession } from '../../api/client';
import { Composer } from '../Composer/Composer';

export function WelcomeView() {
  const { user } = useAuthStore();
  const { startAssessment, loading } = useAssessmentStore();
  const [sessions, setSessions] = useState<UnifiedSession[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [showSessions, setShowSessions] = useState(false);

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

  const handleSend = (text: string) => {
    if (loading) return;
    if (user) {
      startAssessment(user.email, text);
    } else {
      startAssessment('guest', text);
    }
  };

  const handleStartPractice = () => {
    if (loading) return;
    startAssessment('guest');
  };

  const handleRandomQuestion = async () => {
    if (loading) return;
    startAssessment('guest');
  };

  const name = user?.display_name || (user ? user.email.split('@')[0] : '');

  const handleOpen = (s: UnifiedSession) => {
    apiClient
      .openSession(s.id, s.status)
      .then((res) => {
        useAssessmentStore.getState().resumeSession(res);
      })
      .catch(() => undefined);
  };

  const handleClearAll = async () => {
    if (!user) return;
    if (!window.confirm('Delete ALL sessions and assessments for your account? This cannot be undone.')) return;
    try {
      await apiClient.clearCandidateData(user.email);
      setSessions([]);
    } catch {
      // Ignore — list stays as-is.
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col items-center justify-center overflow-y-auto px-4 pb-24">
      <div className="flex w-full max-w-2xl flex-col items-center">
        <h1 className="mb-2 text-2xl font-bold text-[var(--color-text-primary)] md:text-3xl">
          {user ? `Welcome back, ${name}!` : 'What would you like to practice?'}
        </h1>
        <p className="mb-8 text-sm text-[var(--color-text-secondary)]">
          {user
            ? 'Start a scored assessment to track your progress.'
            : 'Try ML interview questions — nothing is scored or saved.'}
        </p>

        <div className="w-full">
          <Composer placeholder="Ask anything about AI, ML, or coding…" onSubmit={handleSend} disabled={loading} />
        </div>

        <div className="mt-3 flex items-center gap-3">
          <button
            onClick={handleRandomQuestion}
            disabled={loading}
            className="flex items-center gap-1.5 rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-3 py-1.5 text-xs text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-accent)]/40 hover:text-[var(--color-accent)] disabled:opacity-40"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
              <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
            </svg>
            Random question
          </button>
          <p className="text-[11px] text-[var(--color-text-muted)]">
            AI Research Coach can make mistakes. Practice isn't scored.
          </p>
        </div>

        {user && loaded && sessions.length > 0 && (
          <div className="mt-8 w-full">
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
                        s.status === 'active'
                          ? 'bg-[var(--color-accent)]/15 text-[var(--color-accent)]'
                          : 'bg-[var(--color-success)]/15 text-[var(--color-success)]'
                      }`}
                    >
                      {s.status === 'active' ? 'IN PROGRESS' : 'DONE'}
                    </span>
                    <span className="min-w-0 flex-1 truncate">
                      {s.score != null && `${(s.score * 100).toFixed(0)}% · `}
                      {new Date(s.updated_at).toLocaleString()}
                    </span>
                  </button>
                ))}
                <button
                  onClick={handleClearAll}
                  className="w-full text-left px-2 pt-1 text-[11px] text-[var(--color-text-muted)] hover:text-[var(--color-error)]"
                >
                  Clear all my data
                </button>
              </div>
            )}
          </div>
        )}

        {!user && (
          <p className="mt-6 text-xs text-[var(--color-text-muted)]">
            Want a scored assessment?{' '}
            <button
              onClick={handleStartPractice}
              className="text-[var(--color-accent)] underline-offset-2 hover:underline"
            >
              Try practice mode
            </button>
          </p>
        )}
      </div>
    </div>
  );
}
