import { useCallback, useMemo, useRef, useState } from 'react';
import Editor, { type OnMount } from '@monaco-editor/react';

interface Props {
  code: string;
  readOnly?: boolean;
  height?: string;
  language?: string;
  onChange?: (code: string) => void;
  /** Grow the editor to fit its content (no inner scroll) instead of a fixed height. */
  fitContent?: boolean;
  /** Show an Undo/Redo toolbar above the editor (curator authoring). */
  historyControls?: boolean;
}

// Approximate geometry of a rendered line (13px font, 1.5 line-height) plus the
// editor's 12px top/bottom padding, used to size the box to its content.
const LINE_HEIGHT = 20;
const VERTICAL_PADDING = 24;
const MIN_HEIGHT = 320;
// Blank lines kept below the last line of code so the scaffold has breathing room.
const MARGIN_LINES = 4;

function fittedHeight(code: string): number {
  const lines = code ? code.split('\n').length : 1;
  return Math.max(MIN_HEIGHT, (lines + MARGIN_LINES) * LINE_HEIGHT + VERTICAL_PADDING);
}

const LANGUAGE_ALIASES: Record<string, string> = {
  'c++': 'cpp',
  cxx: 'cpp',
  cc: 'cpp',
};

const isMac =
  typeof navigator !== 'undefined' && /Mac|iPhone|iPad|iPod/.test(navigator.platform);
const HISTORY_HINT = isMac ? '⌘Z / ⇧⌘Z' : 'Ctrl+Z / Ctrl+Shift+Z';

export function CodeEditor({
  code,
  readOnly = false,
  height = 'h-64',
  language = 'python',
  onChange,
  fitContent = false,
  historyControls = false,
}: Props) {
  const monacoLanguage = LANGUAGE_ALIASES[language.toLowerCase()] ?? language.toLowerCase();
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);

  // Monaco's own undo stack is the source of truth; keep the toolbar buttons in
  // sync with it. The content-change event fires for typing, paste and undo/redo.
  const syncHistory = useCallback(() => {
    const model = editorRef.current?.getModel();
    setCanUndo(!!model?.canUndo());
    setCanRedo(!!model?.canRedo());
  }, []);

  const handleMount: OnMount = useCallback(
    (editor) => {
      editorRef.current = editor;
      editor.onDidChangeModelContent(syncHistory);
      syncHistory();
    },
    [syncHistory],
  );

  const runHistory = useCallback(
    (id: 'undo' | 'redo') => {
      const editor = editorRef.current;
      if (!editor) return;
      editor.focus();
      editor.trigger('history-controls', id, null);
      syncHistory();
    },
    [syncHistory],
  );

  const options = useMemo(
    () => ({
      fontSize: 13,
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      minimap: { enabled: false },
      scrollBeyondLastLine: false,
      // A content-fitted editor has nothing to scroll itself. Monaco's wheel
      // handler preventDefaults by default (alwaysConsumeMouseWheel: true),
      // which killed page scrolling while the cursor was over the code. Turn
      // both off so the wheel is left untouched and the browser scrolls the
      // page natively — same smoothness as scrolling anywhere else.
      scrollbar: fitContent
        ? { handleMouseWheel: false, alwaysConsumeMouseWheel: false }
        : undefined,
      padding: { top: 12, bottom: 12 },
      lineNumbers: 'on' as const,
      renderLineHighlight: 'line' as const,
      bracketPairColorization: { enabled: true },
      automaticLayout: true,
      tabSize: 4,
      readOnly,
    }),
    [fitContent, readOnly],
  );

  const showHistory = historyControls && !readOnly;

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--color-border-default)]">
      {showHistory && (
        <div className="flex items-center gap-1 border-b border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-1.5 py-1">
          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => runHistory('undo')}
            disabled={!canUndo}
            aria-label="Undo starter code change"
            title="Undo"
            className="rounded-md border border-[var(--color-border-default)] px-2 py-0.5 text-[11px] leading-4 text-[var(--color-text-secondary)] transition-colors hover:text-[var(--color-text-primary)] disabled:cursor-default disabled:opacity-30"
          >
            ↶ Undo
          </button>
          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => runHistory('redo')}
            disabled={!canRedo}
            aria-label="Redo starter code change"
            title="Redo"
            className="rounded-md border border-[var(--color-border-default)] px-2 py-0.5 text-[11px] leading-4 text-[var(--color-text-secondary)] transition-colors hover:text-[var(--color-text-primary)] disabled:cursor-default disabled:opacity-30"
          >
            ↷ Redo
          </button>
          <span className="ml-auto pr-1 text-[10px] text-[var(--color-text-muted)]">
            {HISTORY_HINT}
          </span>
        </div>
      )}
      <div
        className={fitContent ? '' : height}
        style={fitContent ? { height: `${fittedHeight(code)}px` } : undefined}
      >
        <Editor
          height="100%"
          language={monacoLanguage}
          theme="light"
          value={code}
          onChange={(v) => onChange?.(v ?? '')}
          onMount={handleMount}
          options={options}
        />
      </div>
    </div>
  );
}
