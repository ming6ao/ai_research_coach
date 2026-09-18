/**
 * Helpers for curator quick task authoring (`POST /api/v1/tasks/draft`).
 *
 * Kept free of React so the parsing rules are unit-testable on their own.
 */

/**
 * Split curator-entered text into step prompts.
 *
 * Steps are separated by a standalone `---` line when one is present,
 * otherwise by a blank line. Blank input yields no steps; a single block is a
 * one-step task. Order is preserved.
 */
export function splitStepPrompts(text: string): string[] {
  const normalized = (text ?? '').replace(/\r\n/g, '\n').trim();
  if (!normalized) return [];
  const blocks = /\n\s*-{3,}\s*\n/.test(normalized)
    ? normalized.split(/\n\s*-{3,}\s*\n/)
    : normalized.split(/\n\s*\n/);
  return blocks.map((block) => block.trim()).filter((block) => block.length > 0);
}

export interface DraftStepLike {
  key: string;
  prompt: string;
  primary: string;
  scaffold: string;
}

/**
 * First blocking problem in the curator's step drafts, or null when the form
 * is ready to submit. Empty trailing steps are ignored. Includes the step
 * index so the editor can focus the offending step.
 */
export function findStepDraftError(
  steps: DraftStepLike[],
): { index: number; message: string } | null {
  const seen = new Set<string>();
  for (let i = 0; i < steps.length; i += 1) {
    const key = steps[i].key.trim();
    const hasPrompt = steps[i].prompt.trim().length > 0;
    if (!key && !hasPrompt) continue;
    if (!key || !hasPrompt) {
      return { index: i, message: 'Every step needs both a key and a prompt.' };
    }
    if (seen.has(key)) {
      return { index: i, message: `Two steps share the same key: ${key}` };
    }
    seen.add(key);
    if (!steps[i].primary) {
      return { index: i, message: `Step ${i + 1} needs a primary skill.` };
    }
    if (!steps[i].scaffold.trim()) {
      return { index: i, message: `Step ${i + 1} needs starter code.` };
    }
  }
  return null;
}
