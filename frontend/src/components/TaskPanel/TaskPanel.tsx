import type { Task } from '../../api/client';
import { CodeTask } from './CodeTask';

interface Props {
  task: Task;
  onSubmit: (taskId: string, answer: string, hintsUsed: string[]) => void;
  onSkip?: () => void;
  onEndPractice?: () => void;
  mode: 'assessment' | 'practice';
  disabled: boolean;
}

export function TaskPanel({ task, onSubmit, onSkip, onEndPractice, mode, disabled }: Props) {
  return (
    <CodeTask
      task={task}
      onSubmit={onSubmit}
      onSkip={onSkip}
      onEndPractice={onEndPractice}
      mode={mode}
      disabled={disabled}
    />
  );
}
