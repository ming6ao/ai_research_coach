/**
 * Selection helpers for the "Explain this" feature.
 *
 * Kept dependency-free (no React / no DOM at module scope) so the pure text
 * helpers are unit-testable with the repo's zero-dependency Node test runner.
 */

/** Hard cap on the highlighted passage sent for explanation. */
export const MAX_SELECTION = 4000;

/** Hard cap on the enclosing-paragraph context sent alongside a selection. */
export const MAX_CONTEXT = 800;

/**
 * Collapse whitespace and trim. Rendered markdown/KaTeX selections arrive with
 * arbitrary newlines and indentation; the LLM wants a single clean passage.
 */
export function normalizeSelectionText(raw: string): string {
  return (raw ?? '').replace(/\s+/g, ' ').trim();
}

/** Normalize + cap the enclosing context (never longer than MAX_CONTEXT). */
export function clampContext(raw: string): string {
  return normalizeSelectionText(raw).slice(0, MAX_CONTEXT);
}

/** Serialize a DOM selection Range, preferring LaTeX for rendered equations. */
export function serializeRange(range: Range): string {
  const fragment = range.cloneContents();
  const parts: string[] = [];

  const walk = (node: Node): void => {
    if (node.nodeType === Node.TEXT_NODE) {
      parts.push(node.textContent ?? '');
      return;
    }
    if (node.nodeType === Node.ELEMENT_NODE) {
      const el = node as Element;
      // KaTeX paints a MathML copy plus an aria-hidden visual copy; reading
      // both duplicates and garbles equations. Prefer the original LaTeX.
      if (el.getAttribute('aria-hidden') === 'true') return;
      const latex = el.getAttribute('data-latex');
      if (latex != null) {
        parts.push(`$${latex}$`);
        return;
      }
      if (el.classList.contains('katex')) {
        const annotation = el.querySelector('annotation[encoding="application/x-tex"]');
        if (annotation?.textContent) {
          parts.push(`$${annotation.textContent}$`);
          return;
        }
      }
    }
    // Recurse for elements *and* the top-level DocumentFragment returned by
    // cloneContents() (nodeType 11) — otherwise nothing is ever visited.
    node.childNodes.forEach(walk);
  };

  walk(fragment);
  return normalizeSelectionText(parts.join(''));
}

/**
 * Write `text` to the clipboard. Uses the async Clipboard API where available
 * and falls back to a hidden textarea so the "Copy" action also works over
 * plain http / older browsers. Returns whether the write succeeded.
 */
export async function copyText(text: string): Promise<boolean> {
  if (!text) return false;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Permission denied or insecure context — fall through to the legacy path.
  }
  try {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.top = '-9999px';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    area.remove();
    return ok;
  } catch {
    return false;
  }
}
