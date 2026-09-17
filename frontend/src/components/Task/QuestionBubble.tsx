import { Fragment, type ReactNode } from 'react';
import type { Task, TaskPart, TaskTags } from '../../api/client';
import { Markdown } from '../Markdown/Markdown';
import { TagChips } from './TagChips';

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
  prompt: string;
  /** The step(s) to show. Callers pass only what the learner would see. */
  parts?: TaskPart[];
  tags?: TaskTags;
  remediation?: Task['remediation'];
  phaseIndex?: number;
  phaseTotal?: number;
  /** Curator slot: when provided, replaces the rendered markdown prompt. */
  renderPrompt?: (prompt: string) => ReactNode;
  /** Curator slot: when provided, replaces a numbered part's list item. */
  renderPart?: (part: TaskPart, index: number) => ReactNode;
}

/**
 * The single source of truth for how a question is presented to a learner:
 * a coach bubble with a "Question" header, optional step badge / follow-up
 * label, the markdown prompt, a numbered parts list and the tag chips.
 * `ChatView` uses it read-only; the curator editor injects editable slots.
 */
export function QuestionBubble({
  prompt,
  parts,
  tags,
  remediation,
  phaseIndex,
  phaseTotal,
  renderPrompt,
  renderPart,
}: Props) {
  const label = followUpLabel(remediation);
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
        {renderPrompt ? renderPrompt(prompt) : <Markdown text={prompt} size="lg" />}
        {parts && parts.length > 0 && (
          <ol className="space-y-1 border-l border-[var(--color-border-default)] pl-3">
            {parts.map((part, i) =>
              renderPart ? (
                <Fragment key={part.key || i}>{renderPart(part, i)}</Fragment>
              ) : (
                <li
                  key={part.key}
                  className="text-[15px] leading-6 text-[var(--color-text-secondary)]"
                >
                  <span className="font-semibold text-[var(--color-text-primary)]">
                    {i + 1}. {part.key}
                  </span>
                  {' — '}
                  {part.prompt}
                </li>
              ),
            )}
          </ol>
        )}
        <TagChips tags={tags} />
      </div>
    </CoachBubble>
  );
}
