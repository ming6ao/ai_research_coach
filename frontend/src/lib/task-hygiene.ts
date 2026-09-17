const PRIVATE_SECTION = /(^|\n)\s*(private|protected)\s*:/m;
const MEMBER_FIELD = /(^|\n)\s*(?:mutable\s+)?[\w:<>,\s*&]+\s+\w+_\s*(?:=|;)/m;
const SELF_ATTRIBUTE = /(^|\n)\s*self\.\w+\s*=/m;

/**
 * Heuristics for starter-code hygiene. A scaffold should describe the public
 * API (with comments) and leave the internal representation to the learner —
 * private sections and member fields hand over the answer being evaluated.
 * Returns human-readable issue descriptions; empty when nothing looks off.
 */
export function scaffoldHygieneIssues(scaffold: string | undefined | null): string[] {
  const text = scaffold ?? '';
  if (!text.trim()) return [];
  const issues: string[] = [];
  if (PRIVATE_SECTION.test(text)) {
    issues.push(
      'a private/protected section — keep the API public and let learners design the internals',
    );
  }
  if (MEMBER_FIELD.test(text)) {
    issues.push('member fields — the data structures are part of the answer');
  }
  if (SELF_ATTRIBUTE.test(text)) {
    issues.push('instance attributes — the state layout is part of the answer');
  }
  return issues;
}
