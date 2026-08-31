import type { Hint } from '../../api/client';
import { Markdown } from '../Markdown/Markdown';

interface Props {
  hints: Hint[];
  viewed: Set<string>;
  disabled: boolean;
  onRevealHint: (id: string) => void;
  mode: 'assessment' | 'practice';
}

export function HintSection({ hints, viewed, disabled, onRevealHint, mode }: Props) {
  const hiddenCount = hints.length - viewed.size;
  const nextHint = hints.find((h) => !viewed.has(h.id));

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Help
        </p>
        {hiddenCount > 0 && (
          <p className="text-[11px] text-[var(--color-text-muted)]">
            {hiddenCount} more available
          </p>
        )}
      </div>
      {hints.map(
        (hint) =>
          viewed.has(hint.id) && (
            <div
              key={hint.id}
              className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] px-3 py-2"
            >
              <Markdown text={hint.text} />
            </div>
          )
      )}
      {nextHint && (
        <button
          onClick={() => onRevealHint(nextHint.id)}
          disabled={disabled}
          className="rounded-lg border border-dashed border-[var(--color-border-default)] px-3 py-2 text-sm text-[var(--color-text-muted)] transition-colors hover:border-[var(--color-accent)]/50 hover:text-[var(--color-accent)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          + Request hint
        </button>
      )}
      {viewed.size > 0 && mode === 'assessment' && (
        <p className="text-[11px] text-[var(--color-text-muted)]">
          Using help adjusts your mastery for this task.
        </p>
      )}
    </div>
  );
}