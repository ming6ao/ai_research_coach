import type { Task } from '../../api/client';
import { MCQTask } from './MCQTask';
import { CodeTask } from './CodeTask';
import { OpenTask } from './OpenTask';

interface Props {
  task: Task;
  onSubmit: (taskId: string, answer: string) => void;
  disabled: boolean;
}

export function TaskPanel({ task, onSubmit, disabled }: Props) {
  switch (task.type) {
    case 'mcq':
      return <MCQTask task={task} onSubmit={onSubmit} disabled={disabled} />;
    case 'code':
      return <CodeTask task={task} onSubmit={onSubmit} disabled={disabled} />;
    case 'open':
      return <OpenTask task={task} onSubmit={onSubmit} disabled={disabled} />;
    default:
      return (
        <div className="flex h-full items-center justify-center text-[var(--color-text-muted)]">
          Unknown task type: {(task as Task).type}
        </div>
      );
  }
}
