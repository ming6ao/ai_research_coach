/**
 * Tailwind classes for markdown lists.
 *
 * Tailwind v4's preflight resets `ul`/`ol`/`menu` to `list-style: none`, so
 * the shared `Markdown` renderer has to opt back in for the markers to be
 * visible. Kept here (rather than inline in the TSX) so the class strings can
 * be unit-tested without a JSX-capable runner.
 */
export const LIST_CLASSES = {
  ul: 'my-2 list-disc space-y-1 pl-5',
  ol: 'my-2 list-decimal space-y-1 pl-5',
} as const;
