import { useState, useEffect, useRef } from 'react';
import type { Task } from '../../api/client';

interface Props {
  task: Task;
  onSubmit: (taskId: string, answer: string) => void;
  disabled: boolean;
}

export function OpenTask({ task, onSubmit, disabled }: Props) {
  const [answer, setAnswer] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setAnswer('');
  }, [task.id]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = textareaRef.current.scrollHeight + 'px';
    }
  }, [answer]);

  const handleSubmit = () => {
    if (answer.trim()) {
      onSubmit(task.id, answer.trim());
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex-1 overflow-y-auto pr-2">
        <p className="mb-4 text-lg leading-relaxed text-[var(--color-text-primary)]">
          {task.prompt}
        </p>
      </div>

      <textarea
        ref={textareaRef}
        value={answer}
        onChange={(e) => setAnswer(e.target.value)}
        disabled={disabled}
        placeholder="Type your answer here..."
        rows={6}
        className="w-full resize-none rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-4 font-mono text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-muted)] focus:border-[var(--color-border-focus)] focus:outline-none disabled:opacity-60"
      />

      <div className="flex items-center justify-between border-t border-[var(--color-border-default)] pt-3">
        <span className="text-xs text-[var(--color-text-muted)]">
          {answer.length} characters
        </span>
        <button
          onClick={handleSubmit}
          disabled={disabled || !answer.trim()}
          className="rounded-lg bg-[var(--color-accent)] px-6 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          Submit Answer
        </button>
      </div>
    </div>
  );
}
