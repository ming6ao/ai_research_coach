import ReactMarkdown from 'react-markdown';
import { CodeBlock } from '../CodeBlock/CodeBlock';
import { normalizeMarkdownFences, splitMathChildren } from '../../lib/markdown';

interface Props {
  text: string;
  className?: string;
}

export function Markdown({ text, className = '' }: Props) {
  return (
    <div
      className={`text-sm leading-6 text-[var(--color-text-secondary)] ${className}`}
    >
      <ReactMarkdown
        components={{
          pre({ children }) {
            return <>{children}</>;
          },
          code({ className: cls, children, ...props }) {
            const raw = String(children);
            const lang = /language-(\w+)/.exec(cls ?? '')?.[1];
            const isBlock = Boolean(lang) || raw.includes('\n');
            if (isBlock) {
              return <CodeBlock code={raw} language={lang ?? 'python'} />;
            }
            return (
              <code
                className="rounded bg-[var(--color-bg-tertiary)] px-1.5 py-0.5 font-mono text-[1em] text-[var(--color-text-primary)]"
                {...props}
              >
                {children}
              </code>
            );
          },
          p: ({ children }) => <p>{splitMathChildren(children)}</p>,
          li: ({ children }) => <li>{splitMathChildren(children)}</li>,
          h1: ({ children }) => <h1>{splitMathChildren(children)}</h1>,
          h2: ({ children }) => <h2>{splitMathChildren(children)}</h2>,
          h3: ({ children }) => <h3>{splitMathChildren(children)}</h3>,
          h4: ({ children }) => <h4>{splitMathChildren(children)}</h4>,
          strong: ({ children }) => <strong>{splitMathChildren(children)}</strong>,
          em: ({ children }) => <em>{splitMathChildren(children)}</em>,
          blockquote: ({ children }) => <blockquote>{splitMathChildren(children)}</blockquote>,
        }}
      >
        {normalizeMarkdownFences(text)}
      </ReactMarkdown>
    </div>
  );
}