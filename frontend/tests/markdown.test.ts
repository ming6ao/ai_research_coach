import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { ReactNode } from 'react';
import React from 'react';
import { renderToString } from 'react-dom/server';
import ReactMarkdown from 'react-markdown';
import { normalizeMarkdownFences } from '../src/lib/markdown-fences.ts';
import { LIST_CLASSES } from '../src/lib/markdown-lists.ts';
import { MARKDOWN_SIZE_CLASSES } from '../src/lib/markdown-sizes.ts';

test('markdown exposes a medium coach-reading size', () => {
  assert.match(MARKDOWN_SIZE_CLASSES.md, /text-\[15px\]/);
  assert.match(MARKDOWN_SIZE_CLASSES.md, /leading-7/);
  assert.match(MARKDOWN_SIZE_CLASSES.lg, /text-\[17px\]/);
  assert.match(MARKDOWN_SIZE_CLASSES.sm, /text-sm/);
});

test('inserts a newline before a fence glued to prose', () => {
  const input = 'Here is the correct implementation:```python\ndef f():\n    pass\n```';
  assert.equal(normalizeMarkdownFences(input), 'Here is the correct implementation:\n```python\ndef f():\n    pass\n```');
});

test('inserts a newline before a tilde fence glued to prose', () => {
  const input = 'Try:~~~python\nprint(1)\n~~~';
  assert.equal(normalizeMarkdownFences(input), 'Try:\n~~~python\nprint(1)\n~~~');
});

test('leaves an already well-formed fence unchanged', () => {
  const input = 'Note:\n\n```python\nprint(1)\n```\n';
  assert.equal(normalizeMarkdownFences(input), input);
});

test('leaves a fence at the start of the string unchanged', () => {
  const input = '```python\nprint(1)\n```';
  assert.equal(normalizeMarkdownFences(input), input);
});

test('leaves single-backtick inline code unchanged', () => {
  const input = 'Use `return 1` here.';
  assert.equal(normalizeMarkdownFences(input), input);
});

test('does not touch plain text without fences', () => {
  const input = 'No code here.';
  assert.equal(normalizeMarkdownFences(input), input);
});

test('glued fence renders as a code block after normalization', () => {
  const feedback =
    'You returned 0. Correct implementation:```python\ndef variance(X, ddof=0):\n    mean = sum(X) / len(X)\n    return mean\n```';

  const html = renderToString(
    React.createElement(ReactMarkdown, null, normalizeMarkdownFences(feedback)),
  );

  assert.ok(html.includes('language-python'), 'expected a fenced code block to render');
  assert.ok(html.includes('def variance'), 'expected the code text to be present');
  assert.ok(!html.includes('```'), 'expected the fence backticks not to leak into the output');
});

test('markdown lists opt back into visible markers after the preflight reset', () => {
  const components = {
    ul: (props: { children?: ReactNode }) =>
      React.createElement('ul', { className: LIST_CLASSES.ul }, props.children),
    ol: (props: { children?: ReactNode }) =>
      React.createElement('ol', { className: LIST_CLASSES.ol }, props.children),
  };
  const html = renderToString(
    React.createElement(
      ReactMarkdown,
      { components },
      '- `free(seq_id)` releases every block owned by the sequence.\n\n1. first\n2. second',
    ),
  );
  // Tailwind v4 preflight sets `list-style: none`; without these utilities the
  // bullets are in the DOM but invisible.
  assert.match(html, /<ul class="[^"]*list-disc[^"]*"/);
  assert.match(html, /<ol class="[^"]*list-decimal[^"]*"/);
});