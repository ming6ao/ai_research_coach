import type { Task } from '../../api/client';
import { CodeTask } from './CodeTask';

interface Props {
  task: Task;
  onSubmit: (taskId: string, answer: string, hintsUsed: string[]) => void;
  disabled: boolean;
}

export function TaskPanel({ task, onSubmit, disabled }: Props) {
  return <CodeTask task={task} onSubmit={onSubmit} disabled={disabled} />;
}
