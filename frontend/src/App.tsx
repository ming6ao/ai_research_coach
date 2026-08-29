import { useState, useEffect } from 'react';
import { useAssessmentStore } from './stores/assessmentStore';
import { apiClient, type ActiveSession } from './api/client';
import { Header } from './components/Header/Header';
import { TaskPanel } from './components/TaskPanel/TaskPanel';
import { FeedbackPanel } from './components/FeedbackPanel/FeedbackPanel';
import { ChatLog } from './components/ChatLog/ChatLog';
import { ReportView } from './components/Report/ReportView';
import { Splitter } from './components/Splitter/Splitter';

const roles = [
  { value: 'ml_researcher', label: 'ML Researcher' },
  { value: 'ml_infra_engineer', label: 'ML Infra Engineer' },
];

const roleLabels: Record<string, string> = {
  ml_researcher: 'ML Researcher',
  ml_infra_engineer: 'ML Infra Engineer',
};

function StartScreen() {
  const { startAssessment, resumeSession, loading } = useAssessmentStore();
  const [name, setName] = useState('');
  const [role, setRole] = useState('ml_researcher');
  const [activeSessions, setActiveSessions] = useState<ActiveSession[]>([]);
  const [selectedSession, setSelectedSession] = useState('');
  const [loadingSessions, setLoadingSessions] = useState(true);

  useEffect(() => {
    apiClient.listActiveSessions().then((res) => {
      setActiveSessions(res.sessions);
      setLoadingSessions(false);
    }).catch(() => setLoadingSessions(false));
  }, []);

  const handleStart = () => {
    if (name.trim()) {
      startAssessment(name.trim(), role);
    }
  };

  const handleResume = () => {
    if (selectedSession) {
      resumeSession(selectedSession);
    }
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

        {/* Resume existing session */}
        {activeSessions.length > 0 && (
          <div className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] p-4">
            <label className="mb-2 block text-xs font-semibold text-[var(--color-text-muted)]">
              Resume a Previous Session
            </label>
            <div className="space-y-2">
              <select
                value={selectedSession}
                onChange={(e) => setSelectedSession(e.target.value)}
                className="w-full rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-border-focus)] focus:outline-none"
              >
                <option value="">
                  {loadingSessions ? 'Loading sessions...' : 'Select a session'}
                </option>
                {activeSessions.map((s) => (
                  <option key={s.session_id} value={s.session_id}>
                    {s.candidate} — {roleLabels[s.role] ?? s.role} — {new Date(s.updated_at).toLocaleString()}
                  </option>
                ))}
              </select>
              <button
                onClick={handleResume}
                disabled={!selectedSession || loading}
                className="w-full rounded-lg border border-[var(--color-accent)] bg-[var(--color-accent)]/10 px-4 py-2.5 text-sm font-semibold text-[var(--color-accent)] transition-colors hover:bg-[var(--color-accent)]/20 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Resume
              </button>
            </div>
          </div>
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

        <div className="space-y-4">
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

          <div>
            <label className="mb-1 block text-xs font-semibold text-[var(--color-text-muted)]">
              Target Role
            </label>
            <div className="grid grid-cols-2 gap-2">
              {roles.map((r) => (
                <button
                  key={r.value}
                  onClick={() => setRole(r.value)}
                  className={`rounded-lg border px-4 py-3 text-sm font-medium transition-all ${
                    role === r.value
                      ? 'border-[var(--color-accent)] bg-[var(--color-accent)]/10 text-[var(--color-accent)]'
                      : 'border-[var(--color-border-default)] bg-[var(--color-bg-primary)] text-[var(--color-text-secondary)] hover:border-[var(--color-accent)]/50'
                  }`}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <button
          onClick={handleStart}
          disabled={loading || !name.trim()}
          className="w-full rounded-lg bg-[var(--color-accent)] py-3 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {loading ? 'Starting...' : 'Begin Assessment'}
        </button>
      </div>
    </div>
  );
}

export default function App() {
  const { currentTask, report, submitAnswer, loadReport, loading, sessionId } =
    useAssessmentStore();

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
            {report ? (
              <ReportView />
            ) : currentTask ? (
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
