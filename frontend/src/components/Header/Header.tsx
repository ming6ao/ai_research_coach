import { useAssessmentStore } from '../../stores/assessmentStore';

const TITLE = 'Skills Assessment';

export function Header() {
  const { candidate, mode, taskIndex, totalTasks, skillStates, currentTask, report } = useAssessmentStore();

  const totalScore = Object.values(skillStates).reduce((sum, s) => sum + s.score, 0);
  const skillCount = Object.keys(skillStates).length;
  const avgScore = skillCount > 0 ? totalScore / skillCount : 0;

  const progress = totalTasks > 0 ? (taskIndex / totalTasks) * 100 : 0;
  const isPractice = mode === 'practice';

  if (report) {
    return (
      <header className="border-b border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-6 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="rounded-full bg-[var(--color-accent)] px-3 py-1 text-xs font-semibold text-white">
              COMPLETE
            </span>
            <span className="text-sm text-[var(--color-text-secondary)]">
              {candidate} &middot; {report.title}
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
            {isPractice ? 'Practice' : TITLE}
          </span>
          <span className="text-sm text-[var(--color-text-secondary)]">
            {isPractice ? 'Guest' : candidate}
          </span>
        </div>

        <div className="flex items-center gap-6">
          {currentTask && (
            <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
              <span>{currentTask.skill}</span>
              <span>&middot;</span>
              <span>Difficulty {currentTask.difficulty}</span>
            </div>
          )}

          <div className="flex items-center gap-3">
            <div className="h-2 w-32 overflow-hidden rounded-full bg-[var(--color-bg-tertiary)]">
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
            <div className="text-xs text-[var(--color-text-muted)]">
              Avg: <span className="font-semibold text-[var(--color-text-primary)]">{(avgScore * 100).toFixed(0)}%</span>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
