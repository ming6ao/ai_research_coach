import type { TaskTags } from '../../api/client';

export function TagChips({ tags }: { tags?: TaskTags }) {
  if (!tags || (!tags.primary && (tags.secondary ?? []).length === 0)) return null;
  const all = [tags.primary, ...(tags.secondary ?? [])].filter(Boolean);
  return (
    <span className="mt-1 flex flex-wrap gap-1">
      {all.map((t) => (
        <span
          key={t}
          className="inline-flex items-center rounded-full border border-[var(--color-accent)]/30 bg-[var(--color-accent)]/5 px-2 py-0.5 text-[10px] text-[var(--color-text-muted)]"
        >
          {t}
        </span>
      ))}
    </span>
  );
}