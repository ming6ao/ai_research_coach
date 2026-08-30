/**
 * Ensure fenced code blocks start on their own line.
 *
 * LLMs sometimes glue the opening fence to surrounding prose (e.g.
 * `:```python`), which CommonMark parses as literal inline text instead of a
 * code block — so the "correct implementation" renders as a plain paragraph
 * with visible backticks. Inserting a newline before any fence that is not
 * already at the start of a line lets the markdown parser recognize it.
 */
export function normalizeMarkdownFences(markdown: string): string {
  return markdown.replace(/([^\n])(```|~~~)/g, '$1\n$2');
}