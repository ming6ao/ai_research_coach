import { useState } from 'react';
import type { Task } from '../../api/client';

interface Props {
  task: Task;
  onSubmit: (taskId: string, answer: string) => void;
  disabled: boolean;
}

export function MCQTask({ task, onSubmit, disabled }: Props) {
  const [selected, setSelected] = useState<string | null>(null);

  const options = task.options ?? [];
  const letter = (i: number) => String.fromCharCode(65 + i);

  const handleSubmit = () => {
    if (selected !== null) {
      onSubmit(task.id, selected);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex-1 overflow-y-auto pr-2">
        <p className="mb-6 text-lg leading-relaxed text-[var(--color-text-primary)]">
          {task.prompt}
        </p>

        <div className="space-y-3">
          {options.map((opt, i) => {
            const l = letter(i);
            const isSelected = selected === l;
            return (
              <button
                key={l}
                onClick={() => !disabled && setSelected(l)}
                disabled={disabled}
                className={`flex w-full items-center gap-4 rounded-lg border px-5 py-4 text-left transition-all ${
                  isSelected
                    ? 'border-[var(--color-accent)] bg-[var(--color-accent)]/10 text-[var(--color-text-primary)]'
                    : 'border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:border-[var(--color-accent)]/50 hover:bg-[var(--color-bg-tertiary)]'
                } ${disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'}`}
              >
                <span
                  className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-sm font-semibold ${
                    isSelected
                      ? 'border-[var(--color-accent)] bg-[var(--color-accent)] text-white'
                      : 'border-[var(--color-border-default)] text-[var(--color-text-muted)]'
                  }`}
                >
                  {l}
                </span>
                <span className="text-sm">{opt.replace(/^[A-D]\.\s*/, '')}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex justify-end border-t border-[var(--color-border-default)] pt-4">
        <button
          onClick={handleSubmit}
          disabled={disabled || selected === null}
          className="rounded-lg bg-[var(--color-accent)] px-6 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          Submit Answer
        </button>
      </div>
    </div>
  );
}
