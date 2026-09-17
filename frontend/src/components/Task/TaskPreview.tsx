import type { TaskPart, TaskTags } from '../../api/client';
import { Markdown } from '../Markdown/Markdown';
import { CodeEditor } from '../TaskPanel/CodeEditor';
import { TagChips } from './TagChips';

interface Props {
  prompt: string;
  parts?: TaskPart[];
  tags?: TaskTags;
  scaffold?: string;
  language?: string;
  showScaffold?: boolean;
  phaseIndex?: number;
  phaseTotal?: number;
}

/**
 * Learner-view preview of a task, matching the ChatView question bubble:
 * Question label, markdown prompt, numbered parts list, and tag chips —
 * plus the scaffold shown in the same editor the candidate would see. For a
 * phased task only the active step is shown, with a "Step k of n" header.
 */
export function TaskPreview({
  prompt,
  parts,
  tags,
  scaffold,
  language,
  showScaffold = true,
  phaseIndex = 1,
  phaseTotal = 1,
}: Props) {
  const phased = phaseTotal > 1;
  const visibleParts = phased && parts ? parts.slice(phaseIndex - 1, phaseIndex) : parts;
  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Question
          {phased && (
            <span className="rounded-full border border-[var(--color-border-default)] px-2 py-0.5 text-[10px] font-semibold normal-case tracking-normal text-[var(--color-text-secondary)]">
              Step {phaseIndex} of {phaseTotal}
            </span>
          )}
        </p>
        <Markdown text={prompt} size="lg" />
        {visibleParts && visibleParts.length > 0 && (
          <ol className="space-y-1 border-l border-[var(--color-border-default)] pl-3">
            {visibleParts.map((part, i) => (
              <li key={part.key} className="text-[15px] leading-6 text-[var(--color-text-secondary)]">
                <span className="font-semibold text-[var(--color-text-primary)]">{i + 1}. {part.key}</span>
                {' — '}
                {part.prompt}
              </li>
            ))}
          </ol>
        )}
        <TagChips tags={tags} />
      </div>
      {showScaffold && scaffold ? (
        <div>
          <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
            Starter code
          </p>
          <CodeEditor code={scaffold} language={language} readOnly height="h-40" />
        </div>
      ) : null}
    </div>
  );
}