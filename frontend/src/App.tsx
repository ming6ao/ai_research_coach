import { useState, useEffect, useCallback } from 'react';
import { useAssessmentStore } from './stores/assessmentStore';
import { apiClient, type UnifiedSession } from './api/client';
import { Header } from './components/Header/Header';
import { TaskPanel } from './components/TaskPanel/TaskPanel';
import { FeedbackPanel } from './components/FeedbackPanel/FeedbackPanel';
import { ChatLog } from './components/ChatLog/ChatLog';
import { ReportView } from './components/Report/ReportView';
import { Splitter } from './components/Splitter/Splitter';

function StartScreen() {
  const { startAssessment, resumeSession, loading } = useAssessmentStore();
  const [name, setName] = useState('');
  const [sessions, setSessions] = useState<UnifiedSession[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(false);

  const loadSessions = useCallback((candidate: string) => {
    if (!candidate.trim()) {
      setSessions([]);
      return;
    }
    setLoadingSessions(true);
    apiClient.listSessions(candidate.trim())
      .then((res) => setSessions(res.sessions))
      .catch(() => setSessions([]))
      .finally(() => setLoadingSessions(false));
  }, []);

  useEffect(() => {
    const t = setTimeout(() => loadSessions(name), 300);
    return () => clearTimeout(t);
  }, [name, loadSessions]);

  const handleStart = () => {
    if (name.trim()) {
      startAssessment(name.trim());
    }
  };

  const handleClickSession = (session: UnifiedSession) => {
    apiClient.openSession(session.id, session.status).then((res) => {
      resumeSession(res);
    });
  };

  const handleDelete = async (session: UnifiedSession) => {
    if (!window.confirm('Delete this session?')) return;
    if (session.status === 'active') {
      await apiClient.deleteActiveSession(session.id);
    } else {
      await apiClient.deleteAssessment(session.id);
    }
    setSessions((prev) => prev.filter((s) => s.id !== session.id));
  };

  const handleClearAll = async () => {
    const target = name.trim();
    if (!target) return;
    if (!window.confirm(`Delete ALL sessions and assessments for "${target}"? This cannot be undone.`)) return;
    await apiClient.clearCandidateData(target);
    setSessions([]);
  };

  return (
    <div className="flex h-full items-center justify-center">
      <div className="w-full max-w-md space-y-6 rounded-xl border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-8">
        <div className="text-center">
          <h1 className="mb-1 text-2xl font-bold text-[var(--color-text-primary)]">
            AI Research Coach
          </h1>
          <p className="text-sm text-[var(--color-text-secondary)]">
            ML assessment &amp; skill evaluation
          </p>
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold text-[var(--color-text-muted)]">
            Candidate Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleStart()}
            placeholder="Enter your name"
            className="w-full rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] px-4 py-2.5 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-muted)] focus:border-[var(--color-border-focus)] focus:outline-none"
          />
        </div>

        {sessions.length > 0 && (
          <div className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] p-4">
            <label className="mb-2 block text-xs font-semibold text-[var(--color-text-muted)]">
              My Sessions
            </label>
            <div className="space-y-1.5">
              {sessions.map((s) => (
                <div key={s.id} className="flex items-center gap-2">
                  <button
                    onClick={() => handleClickSession(s)}
                    disabled={loading}
                    className="min-w-0 flex-1 truncate rounded border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-3 py-2 text-left text-sm text-[var(--color-text-primary)] hover:border-[var(--color-accent)]/50"
                  >
                    <span className={`mr-1.5 inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                      s.status === 'active'
                        ? 'bg-[var(--color-accent)]/15 text-[var(--color-accent)]'
                        : 'bg-[var(--color-success)]/15 text-[var(--color-success)]'
                    }`}>
                      {s.status === 'active' ? 'ACTIVE' : 'DONE'}
                    </span>
                    {s.score != null && ` — ${(s.score * 100).toFixed(0)}%`}
                    {' — '}
                    {new Date(s.updated_at).toLocaleString()}
                  </button>
                  <button
                    onClick={() => handleDelete(s)}
                    className="shrink-0 rounded border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-2 py-2 text-xs text-[var(--color-text-muted)] hover:border-[var(--color-error)] hover:text-[var(--color-error)]"
                    title="Delete session"
                  >
                    &#x2715;
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {loadingSessions && (
          <p className="text-center text-xs text-[var(--color-text-muted)]">Loading sessions...</p>
        )}

        <div className="relative">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-[var(--color-border-default)]" />
          </div>
          <div className="relative flex justify-center text-xs">
            <span className="bg-[var(--color-bg-secondary)] px-2 text-[var(--color-text-muted)]">
              or start new
            </span>
          </div>
        </div>

        <div className="space-y-2">
          <button
            onClick={handleStart}
            disabled={loading || !name.trim()}
            className="w-full rounded-lg bg-[var(--color-accent)] py-3 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {loading ? 'Starting...' : 'Begin Assessment'}
          </button>

          <button
            onClick={handleClearAll}
            disabled={loading || !name.trim()}
            className="w-full rounded-lg border border-[var(--color-error)]/40 py-2.5 text-sm font-medium text-[var(--color-error)] transition-colors hover:bg-[var(--color-error)]/10 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Clear All My Data
          </button>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const { currentTask, report, submitAnswer, loadReport, loading, sessionId } =
    useAssessmentStore();

  if (report) {
    return (
      <div className="flex h-screen flex-col">
        <Header />
        <div className="flex min-h-0 flex-1">
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="min-h-0 flex-1 overflow-y-auto p-6">
              <ReportView />
            </div>
            <ChatLog />
          </div>
          <Splitter />
          <div className="hidden lg:block flex-1 overflow-y-auto">
            <FeedbackPanel />
          </div>
        </div>
      </div>
    );
  }

  if (!sessionId) {
    return (
      <div className="flex h-screen flex-col">
        <Header />
        <StartScreen />
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col">
      <Header />

      <div className="flex min-h-0 flex-1">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto p-6">
            {currentTask ? (
              <TaskPanel
                key={currentTask.id}
                task={currentTask}
                onSubmit={submitAnswer}
                disabled={loading}
              />
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-4">
                <p className="text-[var(--color-text-secondary)]">
                  All tasks completed.
                </p>
                <button
                  onClick={loadReport}
                  disabled={loading}
                  className="rounded-lg bg-[var(--color-accent)] px-6 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:opacity-40"
                >
                  {loading ? 'Generating...' : 'View Report'}
                </button>
              </div>
            )}
          </div>

          <ChatLog />
        </div>

        <Splitter />

        <div
          className="hidden lg:block flex-1 overflow-y-auto"
        >
          <FeedbackPanel />
        </div>
      </div>
    </div>
  );
}
