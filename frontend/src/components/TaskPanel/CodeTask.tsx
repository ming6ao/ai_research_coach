import { useState } from 'react';
import Editor from '@monaco-editor/react';
import 'katex/dist/katex.min.css';
import 'highlight.js/styles/vs2015.css';
import type { Task } from '../../api/client';
import { Markdown } from '../Markdown/Markdown';

interface Props {
  task: Task;
  onSubmit: (taskId: string, answer: string, hintsUsed: string[]) => void;
  onPracticeSubmit?: (taskId: string, answer: string, hintsUsed: string[]) => void;
  onSkip?: () => void;
  onEndPractice?: () => void;
  mode: 'assessment' | 'practice';
  disabled: boolean;
}

export function CodeTask({ task, onSubmit, onPracticeSubmit, onSkip, onEndPractice, mode, disabled }: Props) {
  const [code, setCode] = useState(task.scaffold ?? '');
  const [viewed, setViewed] = useState<Set<string>>(
    () => new Set((task.hints ?? []).filter((h) => h.pre_revealed).map((h) => h.id))
  );

  const hints = task.hints ?? [];
  const hiddenCount = hints.length - viewed.size;
  const nextHint = hints.find((h) => !viewed.has(h.id));

  const revealHint = (id: string) => {
    setViewed((prev) => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });
  };

  const handleSubmit = () => {
    onSubmit(task.id, code, Array.from(viewed));
  };

  const handlePracticeSubmit = () => {
    if (onPracticeSubmit) {
      onPracticeSubmit(task.id, code, Array.from(viewed));
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="mb-3 flex-1 overflow-y-auto pr-2">
        <p className="mb-4 text-lg leading-relaxed text-[var(--color-text-primary)]">
          {task.prompt}
        </p>

        {hints.length > 0 && (
          <div className="mb-4 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                Help
              </p>
              {hiddenCount > 0 && (
                <p className="text-xs text-[var(--color-text-muted)]">
                  {hiddenCount} more available on request
                </p>
              )}
            </div>
            {hints.map((hint) =>
              viewed.has(hint.id) && (
                <div
                  key={hint.id}
                  className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-3 py-2"
                >
                  <Markdown text={hint.text} />
                </div>
              )
            )}
            {nextHint && (
              <button
                onClick={() => revealHint(nextHint.id)}
                disabled={disabled}
                className="rounded-lg border border-dashed border-[var(--color-border-default)] px-3 py-2 text-sm text-[var(--color-text-muted)] transition-colors hover:border-[var(--color-accent)]/50 hover:text-[var(--color-accent)] disabled:cursor-not-allowed disabled:opacity-40"
              >
                &#43; Request hint
              </button>
            )}
            {viewed.size > 0 && mode === 'assessment' && (
              <p className="text-xs text-[var(--color-text-muted)]">
                Using help adjusts your mastery for this task.
              </p>
            )}
          </div>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-[var(--color-border-default)]">
        <Editor
          height="100%"
          defaultLanguage="python"
          theme="vs-dark"
          value={code}
          onChange={(v) => setCode(v ?? '')}
          onMount={() => undefined}
          options={{
            fontSize: 14,
            fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            padding: { top: 12, bottom: 12 },
            lineNumbers: 'on',
            renderLineHighlight: 'line',
            bracketPairColorization: { enabled: true },
            automaticLayout: true,
            tabSize: 4,
            readOnly: disabled,
          }}
        />
      </div>

      <div className="flex items-center justify-between border-t border-[var(--color-border-default)] pt-3">
        <p className="text-xs text-[var(--color-text-muted)]">
          {mode === 'practice'
            ? 'Anonymous practice — check your answer or skip; nothing is scored or saved.'
            : 'Write your solution in the editor above, then submit.'}
        </p>
        {mode === 'practice' ? (
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={onEndPractice}
              disabled={disabled}
              className="rounded-lg border border-[var(--color-border-default)] px-4 py-2.5 text-sm font-medium text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-border-focus)] hover:text-[var(--color-text-primary)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              End practice
            </button>
            <button
              onClick={onSkip}
              disabled={disabled}
              className="rounded-lg border border-[var(--color-border-default)] px-4 py-2.5 text-sm font-medium text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-border-focus)] hover:text-[var(--color-text-primary)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              Skip &rarr;
            </button>
            <button
              onClick={handlePracticeSubmit}
              disabled={disabled || !code.trim()}
              className="rounded-lg bg-[var(--color-accent)] px-6 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              Check my answer
            </button>
          </div>
        ) : (
          <button
            onClick={handleSubmit}
            disabled={disabled || !code.trim()}
            className="rounded-lg bg-[var(--color-accent)] px-6 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            Submit
          </button>
        )}
      </div>
    </div>
  );
}