import { useEffect, useRef, useState } from 'react';
import { useAssessmentStore, getStoredSessionId } from './stores/assessmentStore';
import { useAuthStore } from './stores/authStore';
import { apiClient, setAuthToken } from './api/client';
import { Header } from './components/Header/Header';
import { ChatView } from './components/Chat/ChatView';
import { WelcomeView } from './components/Chat/WelcomeView';
import { AuthModal } from './components/Auth/AuthModal';
import { ReportView } from './components/Report/ReportView';

function OfflineBanner() {
  const [online, setOnline] = useState(() => navigator.onLine);

  useEffect(() => {
    const goOnline = () => setOnline(true);
    const goOffline = () => setOnline(false);
    window.addEventListener('online', goOnline);
    window.addEventListener('offline', goOffline);
    return () => {
      window.removeEventListener('online', goOnline);
      window.removeEventListener('offline', goOffline);
    };
  }, []);

  if (online) return null;
  return (
    <div className="bg-[var(--color-error)] px-4 py-1.5 text-center text-xs font-medium text-white">
      You&rsquo;re offline. The app is cached, but practice and assessment need a connection.
    </div>
  );
}

function Splash() {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-2">
      <div className="text-2xl font-bold text-[var(--color-text-primary)]">AI Research Coach</div>
      <p className="text-sm text-[var(--color-text-secondary)]">Loading...</p>
    </div>
  );
}

export default function App() {
  const { report, sessionId, mode, startAssessment, resumeSession, endPractice, error } =
    useAssessmentStore();
  const { user, authLoading, restore } = useAuthStore();
  const [authModal, setAuthModal] = useState<null | 'login' | 'signup'>(null);
  const [restored, setRestored] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    if (token) {
      setAuthToken(token);
      window.history.replaceState({}, '', window.location.pathname);
    }
    restore().finally(() => setRestored(true));
  }, [restore]);

  // Boot: resume a stored session or, for guests, start a practice session.
  const bootLock = useRef(false);
  useEffect(() => {
    if (!restored || authLoading) return;
    if (user || sessionId) return;
    if (bootLock.current) return;
    bootLock.current = true;
    const stored = getStoredSessionId();
    const boot = stored
      ? apiClient
          .openSession(stored, 'active')
          .then((res) => {
            if (res.mode !== 'practice') {
              // Guests can't adopt a named (assessment) session — stay a guest.
              localStorage.removeItem('ai_coach_session_id');
              return startAssessment('guest', 'practice');
            }
            resumeSession(res);
          })
          .catch(() => {
            localStorage.removeItem('ai_coach_session_id');
            if (!user) return startAssessment('guest', 'practice');
          })
      : startAssessment('guest', 'practice');
    boot.finally(() => {
      bootLock.current = false;
    });
  }, [restored, authLoading, user, sessionId, resumeSession, startAssessment]);

  // Drop an in-progress guest practice session when the user logs in.
  useEffect(() => {
    if (user && sessionId && mode === 'practice') {
      endPractice();
    }
  }, [user, sessionId, mode, endPractice]);

  if (report) {
    return (
      <div className="flex h-screen flex-col">
        <Header onOpenAuth={setAuthModal} />
        <OfflineBanner />
        <div className="min-h-0 flex-1 overflow-y-auto">
          <ReportView />
        </div>
      </div>
    );
  }

  if (!restored) {
    return <Splash />;
  }

  const showAuthModal = authModal !== null;

  return (
    <div className="flex h-screen flex-col">
      <Header onOpenAuth={setAuthModal} />
      <OfflineBanner />

      {sessionId ? (
        <ChatView />
      ) : user ? (
        <WelcomeView />
      ) : error ? (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 p-6">
          <p className="max-w-md text-center text-sm text-[var(--color-error)]">{error}</p>
          <button
            onClick={() => startAssessment('guest', 'practice')}
            className="rounded-lg bg-[var(--color-accent)] px-6 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)]"
          >
            Retry practice mode
          </button>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <p className="text-sm text-[var(--color-text-muted)]">Starting practice...</p>
        </div>
      )}

      <AuthModal
        open={showAuthModal}
        initialTab={authModal ?? 'login'}
        onClose={() => setAuthModal(null)}
      />
    </div>
  );
}