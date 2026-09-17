import { useEffect, useState } from 'react';
import { useAssessmentStore } from './stores/assessmentStore';
import { useAuthStore } from './stores/authStore';
import { setAuthToken } from './api/client';
import { Header } from './components/Header/Header';
import { ChatView } from './components/Chat/ChatView';
import { HomeView } from './components/Home/HomeView';
import { AuthModal } from './components/Auth/AuthModal';
import { CuratorView } from './components/Curator/CuratorView';

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
      You're offline. The app is cached, but sessions need a connection.
    </div>
  );
}

function Splash() {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-2">
      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--color-accent)] text-sm font-bold text-white">
        RC
      </div>
      <p className="text-sm text-[var(--color-text-muted)]">Loading…</p>
    </div>
  );
}

export default function App() {
  const { sessionId, error } = useAssessmentStore();
  const { authLoading, restore } = useAuthStore();
  const [authModal, setAuthModal] = useState<null | 'login' | 'signup'>(null);
  const [restored, setRestored] = useState(false);
  const [curatorOpen, setCuratorOpen] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    // Legacy query-token flow (pre-Phase-3 backends); current backends set an
    // HttpOnly cookie and redirect with ?login=success instead.
    const token = params.get('token');
    if (token) {
      setAuthToken(token);
    }
    if (token || params.has('login')) {
      window.history.replaceState({}, '', window.location.pathname);
    }
    restore().finally(() => setRestored(true));
  }, [restore]);

  if (!restored || authLoading) {
    return <Splash />;
  }

  const showAuthModal = authModal !== null;

  return (
    <div className="flex h-screen flex-col">
      <Header
        onOpenAuth={setAuthModal}
        onOpenCurator={() => setCuratorOpen(true)}
      />
      <OfflineBanner />

      {curatorOpen ? (
        <CuratorView onClose={() => setCuratorOpen(false)} />
      ) : sessionId ? (
        <ChatView />
      ) : (
        <HomeView />
      )}

      {error && !sessionId && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 rounded-lg border border-[var(--color-error)]/30 bg-[var(--color-bg-secondary)] px-4 py-2 text-sm text-[var(--color-error)]">
          {error}
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