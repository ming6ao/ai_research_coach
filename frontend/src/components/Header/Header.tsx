import { useAssessmentStore } from '../../stores/assessmentStore';
import { useAuthStore } from '../../stores/authStore';

interface Props {
  onOpenAuth: (tab: 'login' | 'signup') => void;
}

export function Header({ onOpenAuth }: Props) {
  const { mode, taskIndex, totalTasks, report, endPractice } = useAssessmentStore();
  const { user, logout } = useAuthStore();
  const isPractice = mode === 'practice';

  const handleLogout = () => {
    logout();
    endPractice();
  };

  if (report) {
    return (
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-4">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--color-accent)] text-xs font-bold text-white">
            RC
          </div>
          <span className="text-sm font-semibold text-[var(--color-text-primary)]">AI Research Coach</span>
          <span className="rounded-full bg-[var(--color-success)]/15 px-2 py-0.5 text-[10px] font-semibold text-[var(--color-success)]">
            COMPLETE
          </span>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-[var(--color-text-secondary)]">
            {(report.overall_score * 100).toFixed(0)}%
          </span>
          <div className="flex h-7 w-7 items-center justify-center rounded-full border border-[var(--color-border-default)] text-xs text-[var(--color-text-muted)]">
            {(user?.display_name || user?.email || 'U').charAt(0).toUpperCase()}
          </div>
        </div>
      </header>
    );
  }

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-4">
      <div className="flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--color-accent)] text-xs font-bold text-white">
          RC
        </div>
        <span className="text-sm font-semibold text-[var(--color-text-primary)]">AI Research Coach</span>
      </div>

      <div className="flex items-center gap-3">
        {totalTasks > 0 && (
          <span className="rounded-full bg-[var(--color-bg-tertiary)] px-2.5 py-1 text-xs text-[var(--color-text-muted)]">
            Q {Math.min(taskIndex + 1, totalTasks)} / {totalTasks}
            {isPractice && ' · Practice'}
          </span>
        )}

        {user ? (
          <>
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
