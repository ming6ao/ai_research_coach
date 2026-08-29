import { useState } from 'react';
import Editor from '@monaco-editor/react';
import type { Task } from '../../api/client';

interface Props {
  task: Task;
  onSubmit: (taskId: string, answer: string) => void;
  disabled: boolean;
}

export function CodeTask({ task, onSubmit, disabled }: Props) {
  const [code, setCode] = useState(task.scaffold ?? '');

  const handleEditorMount = (_editor: unknown) => {
    // ref kept for potential future focus/imperative actions
  };

  const handleSubmit = () => {
    onSubmit(task.id, code);
  };

  return (
    <div className="flex h-full flex-col">
      <div className="mb-3 flex-1 overflow-y-auto pr-2">
        <p className="mb-4 text-lg leading-relaxed text-[var(--color-text-primary)]">
          {task.prompt}
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-[var(--color-border-default)]">
        <Editor
          height="100%"
          defaultLanguage="python"
          theme="vs-dark"
          value={code}
          onChange={(v) => setCode(v ?? '')}
          onMount={handleEditorMount}
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
          Write your solution in the editor above, then submit.
        </p>
        <button
          onClick={handleSubmit}
          disabled={disabled || !code.trim()}
          className="rounded-lg bg-[var(--color-accent)] px-6 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          Run &amp; Submit
        </button>
      </div>
    </div>
  );
}
