import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  MAX_CONTEXT,
  MAX_SELECTION,
  clampContext,
  normalizeSelectionText,
  serializeRange,
} from '../src/lib/selection.ts';

// Minimal DOM shim so `serializeRange` can be exercised in Node: it reads
// `Node.TEXT_NODE` / `Node.ELEMENT_NODE` at call time. The bug this guards
// against is the top-level DocumentFragment from `cloneContents()` never
// being traversed (which made every real selection serialize to '').
(globalThis as unknown as Record<string, unknown>).Node = {
  TEXT_NODE: 3,
  ELEMENT_NODE: 1,
  DOCUMENT_FRAGMENT_NODE: 11,
};

type FakeNode = Record<string, unknown> & { childNodes: FakeNode[]; textContent: string };

function textNode(text: string): FakeNode {
  return { nodeType: 3, textContent: text, childNodes: [] } as unknown as FakeNode;
}

function element(
  children: FakeNode[],
  opts: { latex?: string; ariaHidden?: string; katex?: boolean; annotation?: string } = {},
): FakeNode {
  return {
    nodeType: 1,
    textContent: children.map((c) => c.textContent).join(''),
    childNodes: children,
    getAttribute(name: string) {
      if (name === 'data-latex' && opts.latex != null) return opts.latex;
      if (name === 'aria-hidden' && opts.ariaHidden != null) return opts.ariaHidden;
      return null;
    },
    classList: { contains: (c: string) => opts.katex === true && c === 'katex' },
    querySelector: () => (opts.annotation ? { textContent: opts.annotation } : null),
  } as unknown as FakeNode;
}

function fragment(children: FakeNode[]): FakeNode {
  return {
    nodeType: 11,
    textContent: children.map((c) => c.textContent).join(''),
    childNodes: children,
  } as unknown as FakeNode;
}

function rangeOf(root: FakeNode): Range {
  return { cloneContents: () => root } as unknown as Range;
}

test('serializeRange traverses the top-level DocumentFragment', () => {
  // This is what a real `range.cloneContents()` returns: nodeType 11.
  const root = fragment([textNode('gradient '), element([textNode('descent')])]);
  assert.equal(serializeRange(rangeOf(root)), 'gradient descent');
});

test('serializeRange skips aria-hidden KaTeX copies and keeps the LaTeX', () => {
  const root = fragment([
    textNode('loss '),
    element([textNode('x')], { latex: 'x^2' }),
    element([textNode('garbled')], { ariaHidden: 'true' }),
  ]);
  assert.equal(serializeRange(rangeOf(root)), 'loss $x^2$');
});

test('serializeRange reads the annotation when only a .katex node is present', () => {
  const root = fragment([element([], { katex: true, annotation: '\\frac{a}{b}' })]);
  assert.equal(serializeRange(rangeOf(root)), '$\\frac{a}{b}$');
});

test('collapses whitespace and trims a markdown selection', () => {
  assert.equal(
    normalizeSelectionText('  gradient\n\tdescent   with\n momentum '),
    'gradient descent with momentum',
  );
});

test('leaves an already-clean passage unchanged', () => {
  assert.equal(normalizeSelectionText('mean squared error'), 'mean squared error');
});

test('handles undefined/empty input safely', () => {
  assert.equal(normalizeSelectionText(''), '');
  assert.equal(normalizeSelectionText(undefined as unknown as string), '');
});

test('clampContext caps the enclosing paragraph at the limit', () => {
  const long = 'word '.repeat(400);
  const clamped = clampContext(long);
  assert.equal(clamped.length, MAX_CONTEXT);
  assert.ok(clamped.startsWith('word word'));
});

test('selection limits match the documented caps', () => {
  assert.equal(MAX_SELECTION, 4000);
  assert.equal(MAX_CONTEXT, 800);
});
