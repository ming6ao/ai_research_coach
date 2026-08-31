import hljs from 'highlight.js/lib/core';
import python from 'highlight.js/lib/languages/python';

hljs.registerLanguage('python', python);

interface CodeBlockProps {
  code: string;
  language?: string;
}

export function CodeBlock({ code, language = 'python' }: CodeBlockProps) {
  const trimmed = code.replace(/\n$/, '');
  const html = hljs.getLanguage(language)
    ? hljs.highlight(trimmed, { language }).value
    : hljs.highlightAuto(trimmed).value;

  return (
    <div className="overflow-auto rounded-lg border border-[var(--color-border-default)]">
      <pre
        className="m-0 p-3 text-[14px] leading-[1.5] [tab-size:4]"
        style={{
          background: '#f6f8fa',
          fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
        }}
      >
        <code
          className={`language-${language}`}
          dangerouslySetInnerHTML={{ __html: html }}
        />
      </pre>
    </div>
  );
}