import Editor from '@monaco-editor/react';

interface Props {
  code: string;
  readOnly?: boolean;
  height?: string;
  language?: string;
  onChange?: (code: string) => void;
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
}: Props) {
  const monacoLanguage = LANGUAGE_ALIASES[language.toLowerCase()] ?? language.toLowerCase();
  return (
    <div className={`${height} overflow-hidden rounded-lg border border-[var(--color-border-default)]`}>
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