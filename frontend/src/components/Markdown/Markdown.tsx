import type { ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import { CodeBlock } from '../CodeBlock/CodeBlock';
import { normalizeMarkdownFences, splitMathChildren } from '../../lib/markdown';
import { LIST_CLASSES } from '../../lib/markdown-lists';

interface Props {
  text: string;
  className?: string;
  /** Body copy (default) vs a larger, higher-contrast reading size for questions. */
  size?: 'sm' | 'lg';
}

const SIZE_CLASSES: Record<NonNullable<Props['size']>, string> = {
  sm: 'text-sm leading-6 text-[var(--color-text-secondary)]',
  lg: 'text-[17px] leading-7 text-[var(--color-text-primary)]',
};

// Hoisted to module scope so the component *identities* are stable across
// renders. Recreating these inline (as `components={{ p: (...) => ... }}`)
// hands React a new component type on every render, which makes ReactMarkdown
// remount each element and replace its DOM text nodes — collapsing any live
// text selection (e.g. the one the "Explain this" popover needs) so Ctrl+C /
// right-click → Copy silently stops copying.
const MARKDOWN_COMPONENTS = {
  pre({ children }: { children?: ReactNode }) {
    return <>{children}</>;
  },
  code({ className: cls, children, ...props }: { className?: string; children?: ReactNode }) {
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
  p: ({ children }: { children?: ReactNode }) => <p>{splitMathChildren(children)}</p>,
  ul: ({ children }: { children?: ReactNode }) => (
    <ul className={LIST_CLASSES.ul}>{children}</ul>
  ),
  ol: ({ children }: { children?: ReactNode }) => (
    <ol className={LIST_CLASSES.ol}>{children}</ol>
  ),
  li: ({ children }: { children?: ReactNode }) => <li>{splitMathChildren(children)}</li>,
  h1: ({ children }: { children?: ReactNode }) => <h1>{splitMathChildren(children)}</h1>,
  h2: ({ children }: { children?: ReactNode }) => <h2>{splitMathChildren(children)}</h2>,
  h3: ({ children }: { children?: ReactNode }) => <h3>{splitMathChildren(children)}</h3>,
  h4: ({ children }: { children?: ReactNode }) => <h4>{splitMathChildren(children)}</h4>,
  strong: ({ children }: { children?: ReactNode }) => <strong>{splitMathChildren(children)}</strong>,
  em: ({ children }: { children?: ReactNode }) => <em>{splitMathChildren(children)}</em>,
  blockquote: ({ children }: { children?: ReactNode }) => <blockquote>{splitMathChildren(children)}</blockquote>,
};

export function Markdown({ text, className = '', size = 'sm' }: Props) {
  return (
    <div className={`${SIZE_CLASSES[size]} ${className}`}>
      <ReactMarkdown components={MARKDOWN_COMPONENTS}>
        {normalizeMarkdownFences(text)}
      </ReactMarkdown>
    </div>
  );
}