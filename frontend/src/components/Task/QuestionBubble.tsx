import { type ReactNode } from 'react';
import type { Task, TaskPart } from '../../api/client';
import { Markdown } from '../Markdown/Markdown';

/** Coach avatar + content column, shared by every coach-authored bubble. */
export function CoachBubble({ children, wide }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className="flex items-start gap-3">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--color-accent)] text-[10px] font-bold text-white">
        RC
      </div>
      <div
        className={`min-w-0 flex-1 ${wide ? '' : 'max-w-[85%]'} text-sm leading-6 text-[var(--color-text-primary)]`}
      >
        {children}
      </div>
    </div>
  );
}

function followUpLabel(remediation?: Task['remediation']): string | null {
  if (!remediation) return null;
  switch (remediation.kind) {
    case 'escalation':
      return 'Harder follow-up';
    case 'pivot':
      return 'Related follow-up';
    case 'challenge':
      return 'Fresh challenge';
    default:
      return 'Follow-up';
  }
}

interface Props {
  /** The step(s) to show. Only the active/first step is displayed. */
  parts?: TaskPart[];
  remediation?: Task['remediation'];
  phaseIndex?: number;
  phaseTotal?: number;
  /** Curator slot: when provided, replaces the rendered markdown step prompt. */
  renderPrompt?: (prompt: string) => ReactNode;
}

/**
 * The single source of truth for how a question is presented to a learner:
 * a coach bubble with a "Question" header, optional step badge / follow-up
 * label and the active step's markdown prompt. Skill tags are internal and
 * are never shown to the learner.
 *
 * There is no task-level fallback (every task has at least one part); the
 * step prompt the learner answers gets the prominent "question" style. Step
 * keys are internal identifiers and never appear in the UI. `ChatView` uses
 * this read-only; the curator editor injects an editable step-prompt slot.
 */
export function QuestionBubble({
  parts,
  remediation,
  phaseIndex,
  phaseTotal,
  renderPrompt,
}: Props) {
  const label = followUpLabel(remediation);
  const primary = parts?.[0]?.prompt ?? '';
  return (
    <CoachBubble>
      <div className="space-y-1">
        <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Question
          {phaseIndex != null && (phaseTotal ?? 1) > 1 && (
            <span className="rounded-full border border-[var(--color-border-default)] px-2 py-0.5 text-[10px] font-semibold normal-case tracking-normal text-[var(--color-text-secondary)]">
              Step {phaseIndex} of {phaseTotal}
            </span>
          )}
          {label && (
            <span className="inline-flex items-center gap-1 rounded-full border border-[var(--color-accent)]/40 bg-[var(--color-accent)]/10 px-2.5 py-0.5 text-[11px] font-semibold normal-case tracking-normal text-[var(--color-accent)]">
              {label}
            </span>
          )}
        </p>
        {renderPrompt ? renderPrompt(primary) : <Markdown text={primary} size="lg" />}
      </div>
    </CoachBubble>
  );
}
