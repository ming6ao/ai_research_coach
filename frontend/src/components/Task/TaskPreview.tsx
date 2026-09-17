import type { TaskPart, TaskTags } from '../../api/client';
import { Markdown } from '../Markdown/Markdown';
import { CodeEditor } from '../TaskPanel/CodeEditor';
import { TagChips } from './TagChips';

interface Props {
  prompt: string;
  parts?: TaskPart[];
  tags?: TaskTags;
  scaffold?: string;
  showScaffold?: boolean;
}

/**
 * Learner-view preview of a task, matching the ChatView question bubble:
 * Question label, markdown prompt, numbered parts list, and tag chips —
 * plus the scaffold shown in the same editor the candidate would see.
 */
export function TaskPreview({ prompt, parts, tags, scaffold, showScaffold = true }: Props) {
  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Question
        </p>
        <Markdown text={prompt} size="lg" />
        {parts && parts.length > 0 && (
          <ol className="space-y-1 border-l border-[var(--color-border-default)] pl-3">
            {parts.map((part, i) => (
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
          <CodeEditor code={scaffold} readOnly height="h-40" />
        </div>
      ) : null}
    </div>
  );
}