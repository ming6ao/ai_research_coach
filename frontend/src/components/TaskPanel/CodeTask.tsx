import Editor from '@monaco-editor/react';
import 'katex/dist/katex.min.css';
import 'highlight.js/styles/github.css';
import type { Task } from '../../api/client';
import { Markdown } from '../Markdown/Markdown';

interface Props {
  task: Task;
  mode: 'assessment' | 'practice';
  disabled: boolean;
  code: string;
  onChangeCode: (code: string) => void;
  viewed: Set<string>;
  onRevealHint: (id: string) => void;
}

export function CodeTask({ task, mode, disabled, code, onChangeCode, viewed, onRevealHint }: Props) {
  const hints = task.hints ?? [];
  const hiddenCount = hints.length - viewed.size;
  const nextHint = hints.find((h) => !viewed.has(h.id));

  return (
    <div className="flex h-full flex-col">
      {/* Task prompt + hints (scrollable) */}
      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="mb-4">
          <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
            Question · {task.skill}
          </p>
          <p className="text-sm leading-relaxed text-[var(--color-text-primary)]">
            {task.prompt}
          </p>
        </div>

        {hints.length > 0 && (
          <div className="mb-4 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                Help
              </p>
              {hiddenCount > 0 && (
                <p className="text-[11px] text-[var(--color-text-muted)]">
                  {hiddenCount} more available
                </p>
              )}
            </div>
            {hints.map((hint) =>
              viewed.has(hint.id) && (
                <div
                  key={hint.id}
                  className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] px-3 py-2"
                >
                  <Markdown text={hint.text} />
                </div>
              )
            )}
            {nextHint && (
              <button
                onClick={() => onRevealHint(nextHint.id)}
                disabled={disabled}
                className="rounded-lg border border-dashed border-[var(--color-border-default)] px-3 py-2 text-sm text-[var(--color-text-muted)] transition-colors hover:border-[var(--color-accent)]/50 hover:text-[var(--color-accent)] disabled:cursor-not-allowed disabled:opacity-40"
              >
                + Request hint
              </button>
            )}
            {viewed.size > 0 && mode === 'assessment' && (
              <p className="text-[11px] text-[var(--color-text-muted)]">
                Using help adjusts your mastery for this task.
              </p>
            )}
          </div>
        )}
      </div>

      {/* Editor (fills remaining height) */}
      <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-[var(--color-border-default)]">
        <Editor
          height="100%"
          defaultLanguage="python"
          theme="light"
          value={code}
          onChange={(v) => onChangeCode(v ?? '')}
          onMount={() => undefined}
          options={{
            fontSize: 13,
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
    </div>
  );
}
