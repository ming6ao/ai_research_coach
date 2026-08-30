import { Children, type ReactNode } from 'react';
import katex from 'katex';
import { normalizeMarkdownFences } from './markdown-fences';

export { normalizeMarkdownFences };

const MATH_DELIMITERS = [
  { left: '$$', right: '$$', display: true },
  { left: '$', right: '$', display: false },
];

interface MathSegment {
  type: 'text' | 'math';
  value: string;
  display: boolean;
}

function splitMath(text: string): MathSegment[] {
  const segments: MathSegment[] = [];
  let rest = text;
  // eslint-disable-next-line no-constant-condition
  while (true) {
    let next: { left: string; right: string; display: boolean; index: number } | null = null;
    for (const d of MATH_DELIMITERS) {
      const index = rest.indexOf(d.left);
      if (index !== -1 && (next === null || index < next.index)) {
        next = { ...d, index };
      }
    }
    if (next === null) break;
    if (next.index > 0) {
      segments.push({ type: 'text', value: rest.slice(0, next.index), display: false });
      rest = rest.slice(next.index);
    }
    const end = rest.indexOf(next.right, next.left.length);
    if (end === -1) break;
    segments.push({
      type: 'math',
      value: rest.slice(next.left.length, end),
      display: next.display,
    });
    rest = rest.slice(end + next.right.length);
  }
  if (rest !== '') {
    segments.push({ type: 'text', value: rest, display: false });
  }
  return segments;
}

function InlineMath({ latex, display }: { latex: string; display: boolean }) {
  let html: string | null = null;
  try {
    html = katex.renderToString(latex, { throwOnError: false, displayMode: display });
  } catch {
    html = null;
  }
  if (html === null) {
    return <>{latex}</>;
  }
  return <span dangerouslySetInnerHTML={{ __html: html }} />;
}

export function MathText({ text }: { text: string }) {
  const segments = splitMath(text);
  if (segments.length === 1 && segments[0].type === 'text') {
    return <>{text}</>;
  }
  return (
    <>
      {segments.map((segment, i) =>
        segment.type === 'math' ? (
          <InlineMath key={i} latex={segment.value} display={segment.display} />
        ) : (
          segment.value
        ),
      )}
    </>
  );
}

export function splitMathChildren(children: ReactNode): ReactNode {
  return Children.map(children, (child) =>
    typeof child === 'string' ? <MathText text={child} /> : child,
  );
}