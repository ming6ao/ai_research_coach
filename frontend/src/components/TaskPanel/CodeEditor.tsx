import Editor from '@monaco-editor/react';

interface Props {
  code: string;
  readOnly?: boolean;
  height?: string;
  language?: string;
  onChange?: (code: string) => void;
  /** Grow the editor to fit its content (no inner scroll) instead of a fixed height. */
  fitContent?: boolean;
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

export function CodeEditor({
  code,
  readOnly = false,
  height = 'h-64',
  language = 'python',
  onChange,
  fitContent = false,
}: Props) {
  const monacoLanguage = LANGUAGE_ALIASES[language.toLowerCase()] ?? language.toLowerCase();
  return (
    <div
      className={`${fitContent ? '' : height} overflow-hidden rounded-lg border border-[var(--color-border-default)]`}
      style={fitContent ? { height: `${fittedHeight(code)}px` } : undefined}
    >
      <Editor
        height="100%"
        language={monacoLanguage}
        theme="light"
        value={code}
        onChange={(v) => onChange?.(v ?? '')}
        onMount={() => undefined}
        options={{
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
          lineNumbers: 'on',
          renderLineHighlight: 'line',
          bracketPairColorization: { enabled: true },
          automaticLayout: true,
          tabSize: 4,
          readOnly,
        }}
      />
    </div>
  );
}