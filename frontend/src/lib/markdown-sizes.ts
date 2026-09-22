/**
 * Tailwind classes for the shared `Markdown` renderer's reading sizes.
 *
 * Kept here (rather than inline in the TSX) so the class strings can be
 * unit-tested without a JSX-capable runner — mirroring `markdown-lists.ts`.
 *
 * - `sm`: default body copy.
 * - `md`: coach/feedback prose (larger and higher-contrast than body copy).
 * - `lg`: the question prompt.
 */
export const MARKDOWN_SIZE_CLASSES = {
  sm: 'text-sm leading-6 text-[var(--color-text-secondary)]',
  md: 'text-[15px] leading-7 text-[var(--color-text-primary)]',
  lg: 'text-[17px] leading-7 text-[var(--color-text-primary)]',
} as const;

export type MarkdownSize = keyof typeof MARKDOWN_SIZE_CLASSES;
