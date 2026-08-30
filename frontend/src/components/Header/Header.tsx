import { useAssessmentStore } from '../../stores/assessmentStore';
import { useAuthStore } from '../../stores/authStore';

interface Props {
  onOpenAuth: (tab: 'login' | 'signup') => void;
}

const TITLE = 'Skills Assessment';

export function Header({ onOpenAuth }: Props) {
  const { candidate, mode, taskIndex, totalTasks, skillStates, currentTask, report, endPractice } =
    useAssessmentStore();
  const { user, logout } = useAuthStore();

  const totalScore = Object.values(skillStates).reduce((sum, s) => sum + s.score, 0);
  const skillCount = Object.keys(skillStates).length;
  const avgScore = skillCount > 0 ? totalScore / skillCount : 0;

  const progress = totalTasks > 0 ? (taskIndex / totalTasks) * 100 : 0;
  const isPractice = mode === 'practice';

  const handleLogout = () => {
    logout();
    endPractice();
  };

  if (report) {
    return (
      <header className="border-b border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-6 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="rounded-full bg-[var(--color-accent)] px-3 py-1 text-xs font-semibold text-white">
              COMPLETE
            </span>
            <span className="text-sm text-[var(--color-text-secondary)]">
              {user?.display_name || candidate} &middot; {report.title}
            </span>
          </div>
          <div className="text-sm text-[var(--color-text-secondary)]">
            Final Score: <span className="font-semibold text-[var(--color-text-primary)]">{(report.overall_score * 100).toFixed(0)}%</span>
          </div>
        </div>
      </header>
    );
  }

  return (
    <header className="border-b border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-6 py-3">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className={`rounded-full px-3 py-1 text-xs font-semibold ${isPractice ? 'bg-[var(--color-text-muted)]/20 text-[var(--color-text-secondary)]' : 'bg-[var(--color-accent)] text-white'}`}>
            {isPractice ? 'Guest · Practice' : TITLE}
          </span>
          <span className="text-sm text-[var(--color-text-secondary)]">
            {isPractice ? 'No account needed' : user?.display_name || candidate}
          </span>
        </div>

        <div className="flex items-center gap-6">
          {currentTask && (
            <div className="hidden items-center gap-2 text-xs text-[var(--color-text-muted)] md:flex">
              <span>{currentTask.skill}</span>
              <span>&middot;</span>
              <span>Difficulty {currentTask.difficulty}</span>
            </div>
          )}

          <div className="flex items-center gap-3">
            <div className="h-2 w-28 overflow-hidden rounded-full bg-[var(--color-bg-tertiary)]">
              <div
                className="h-full rounded-full bg-[var(--color-accent)] transition-all duration-500"
                style={{ width: `${progress}%` }}
              />
            </div>
            <span className="text-xs text-[var(--color-text-muted)]">
              {isPractice ? `Question ${Math.min(taskIndex + 1, totalTasks)} of ${totalTasks}` : `${taskIndex}/${totalTasks}`}
            </span>
          </div>

          {!isPractice && skillCount > 0 && (
            <div className="hidden text-xs text-[var(--color-text-muted)] lg:block">
              Avg: <span className="font-semibold text-[var(--color-text-primary)]">{(avgScore * 100).toFixed(0)}%</span>
            </div>
          )}

          <div className="flex items-center gap-2">
            {user ? (
              <>
                <span className="hidden max-w-[160px] truncate rounded-lg border border-[var(--color-border-default)] px-3 py-1.5 text-xs text-[var(--color-text-secondary)] sm:block">
                  {user.display_name || user.email}
                </span>
                <button
                  onClick={handleLogout}
                  className="rounded-lg border border-[var(--color-border-default)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-error)] hover:text-[var(--color-error)]"
                >
                  Log out
                </button>
              </>
            ) : (
              <>
                <button
                  onClick={() => onOpenAuth('login')}
                  className="rounded-lg border border-[var(--color-border-default)] px-4 py-1.5 text-sm font-medium text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-border-focus)] hover:text-[var(--color-text-primary)]"
                >
                  Log in
                </button>
                <button
                  onClick={() => onOpenAuth('signup')}
                  className="rounded-lg bg-[var(--color-accent)] px-4 py-1.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)]"
                >
                  Sign up
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}