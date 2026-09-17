import { useEffect, useState } from 'react';
import { useAssessmentStore } from '../../stores/assessmentStore';
import { useAuthStore } from '../../stores/authStore';
import { apiClient } from '../../api/client';

interface Props {
  onOpenAuth: (tab: 'login' | 'signup') => void;
  onOpenAdmin: () => void;
  onOpenCurator: () => void;
}

export function Header({ onOpenAuth, onOpenAdmin, onOpenCurator }: Props) {
  const { sessionId, taskIndex, completeSession, loading, reset } = useAssessmentStore();
  const { user, logout } = useAuthStore();
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    if (!user) {
      setIsAdmin(false);
      return;
    }
    let cancelled = false;
    apiClient.adminWhoami().then(
      (who) => {
        if (!cancelled) setIsAdmin(who.is_admin);
      },
      () => {
        if (!cancelled) setIsAdmin(false);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [user]);

  const handleLogout = () => {
    logout();
    reset();
  };

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-[var(--color-border-default)] bg-[var(--color-bg-primary)] px-4">
      <div className="flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--color-accent)] text-xs font-bold text-white">
          RC
        </div>
        <span className="text-sm font-semibold text-[var(--color-text-primary)]">AI Research Coach</span>
      </div>

      <div className="flex items-center gap-3">
        {sessionId && (
          <span className="rounded-full bg-[var(--color-bg-tertiary)] px-2.5 py-1 text-xs text-[var(--color-text-muted)]">
            Q {taskIndex + 1}
          </span>
        )}
        {sessionId && (
          <button
            onClick={completeSession}
            disabled={loading}
            title="Finish the session and view your progress (the session otherwise keeps going)"
            className="rounded-lg px-3 py-1.5 text-xs text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text-secondary)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            Finish
          </button>
        )}

        {user ? (
          <>
            <button
              onClick={onOpenCurator}
              className="text-xs text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text-secondary)]"
            >
              My questions
            </button>
            {isAdmin && (
              <button
                onClick={onOpenAdmin}
                className="text-xs text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text-secondary)]"
              >
                Admin
              </button>
            )}
            <span className="hidden text-sm text-[var(--color-text-secondary)] sm:block">
              {user.display_name || user.email.split('@')[0]}
            </span>
            <button
              onClick={handleLogout}
              className="rounded-lg px-3 py-1.5 text-xs text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text-secondary)]"
            >
              Log out
            </button>
          </>
        ) : (
          <button
            onClick={() => onOpenAuth('login')}
            className="rounded-lg px-3 py-1.5 text-xs text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text-secondary)]"
          >
            Log in
          </button>
        )}
      </div>
    </header>
  );
}
