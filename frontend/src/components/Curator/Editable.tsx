import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { Taxonomy } from '../../api/client';
import { Markdown } from '../Markdown/Markdown';

const inputCls =
  'w-full rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] px-2 py-1 text-xs text-[var(--color-text-primary)]';

/** Canonical node id: matches ``coach.taxonomy._canon``. */
function canonSkill(raw: string): string {
  return raw.trim().toLowerCase().replace(/[-\s]+/g, '_');
}

/** Groups of ``{ domain, area }`` for the "new skill" area picker. */
function areaOptions(taxonomy: Taxonomy): { domain: string; area: string }[] {
  return taxonomy.domains.flatMap((domain) =>
    Object.keys(taxonomy.tree[domain] ?? {}).map((area) => ({ domain, area })),
  );
}

/**
 * Open skill picker: a native combobox (``input`` + ``datalist``) with the
 * built-in/custom skills, plus an inline "add as new skill" row when the typed
 * value is not in the vocabulary. ``onAddSkill`` persists it under a chosen
 * area and returns the canonical id; omit it to keep the picker read-only.
 */
function SkillCombobox({
  taxonomy,
  value,
  onSelect,
  onAddSkill,
  exclude = [],
  placeholder = 'Search or type a skill…',
  clearOnSelect = false,
}: {
  taxonomy: Taxonomy;
  value: string;
  onSelect: (skill: string) => void;
  onAddSkill?: (skill: string, area: string) => Promise<string>;
  exclude?: string[];
  placeholder?: string;
  clearOnSelect?: boolean;
}) {
  const listId = useId();
  const [draft, setDraft] = useState(value);
  const [lastValue, setLastValue] = useState(value);
  const [area, setArea] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Adjust state when the controlled value changes externally (step switch,
  // AI draft, task load) without an effect.
  if (value !== lastValue) {
    setLastValue(value);
    setDraft(clearOnSelect ? '' : value);
  }

  const known = useMemo(() => new Set(taxonomy.skills), [taxonomy.skills]);
  const candidate = canonSkill(draft);
  const isKnown = candidate !== '' && known.has(candidate);
  const canCreate = !!onAddSkill && draft.trim() !== '' && !isKnown;

  const options = useMemo(() => {
    const out: { skill: string; area: string; domain: string }[] = [];
    for (const domain of taxonomy.domains) {
      for (const [areaName, skills] of Object.entries(taxonomy.tree[domain] ?? {})) {
        for (const skill of skills) {
          if (exclude.includes(skill) || skill === value) continue;
          out.push({ skill, area: areaName, domain });
        }
      }
    }
    return out;
  }, [taxonomy, exclude, value]);

  const handleInput = (raw: string) => {
    setDraft(raw);
    setError(null);
    const c = canonSkill(raw);
    if (c && known.has(c)) {
      onSelect(c);
      if (clearOnSelect) setDraft('');
    }
  };

  const add = async () => {
    if (!onAddSkill || !area) return;
    setBusy(true);
    setError(null);
    try {
      const created = await onAddSkill(draft.trim(), area);
      onSelect(created);
      setDraft(clearOnSelect ? '' : created);
      setArea('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-1">
      <input
        type="text"
        list={listId}
        value={draft}
        onChange={(e) => handleInput(e.target.value)}
        placeholder={placeholder}
        className={inputCls}
        autoComplete="off"
      />
      <datalist id={listId}>
        {options.map((o) => (
          <option key={o.skill} value={o.skill}>
            {`${o.area} · ${o.domain}`}
          </option>
        ))}
      </datalist>
      {canCreate && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="text-[10px] text-[var(--color-text-muted)]">
            New skill “{draft.trim()}” under
          </span>
          <select
            value={area}
            onChange={(e) => setArea(e.target.value)}
            aria-label="Area for the new skill"
            className={`${inputCls} w-auto`}
          >
            <option value="">choose area…</option>
            {areaOptions(taxonomy).map(({ domain, area: a }) => (
              <option key={a} value={a}>
                {`${a} · ${domain}`}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void add()}
            disabled={busy || !area}
            className="rounded-md border border-[var(--color-accent)]/50 px-2 py-0.5 text-[10px] font-semibold text-[var(--color-accent)] disabled:opacity-40"
          >
            {busy ? 'Adding…' : 'Add skill'}
          </button>
        </div>
      )}
      {error && (
        <p className="text-[10px] text-[var(--color-error)]">{error}</p>
      )}
    </div>
  );
}

/**
 * Primary + up to two secondary tag picker. Both use the open skill
 * combobox, so a curator can create a missing skill inline.
 */
export function TagEditor({
  taxonomy,
  primary,
  secondary,
  onPrimary,
  onSecondary,
  onAddSkill,
  primaryLabel = 'primary tag *',
}: {
  taxonomy: Taxonomy;
  primary: string;
  secondary: string[];
  onPrimary: (tag: string) => void;
  onSecondary: (tags: string[]) => void;
  onAddSkill?: (skill: string, area: string) => Promise<string>;
  primaryLabel?: string;
}) {
  const chosen = [primary, ...secondary].filter(Boolean);
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-start gap-1.5">
        <span className="shrink-0 pt-1 text-[10px] uppercase tracking-wide text-[var(--color-text-muted)]">
          {primaryLabel}
        </span>
        <div className="min-w-[10rem] flex-1">
          <SkillCombobox
            taxonomy={taxonomy}
            value={primary}
            onSelect={onPrimary}
            onAddSkill={onAddSkill}
            exclude={secondary}
          />
        </div>
        {secondary.length < 2 && (
          <div className="min-w-[9rem] flex-1">
            <SkillCombobox
              taxonomy={taxonomy}
              value=""
              onSelect={(t) => onSecondary([...secondary, t])}
              onAddSkill={onAddSkill}
              exclude={chosen}
              placeholder="+ secondary tag…"
              clearOnSelect
            />
          </div>
        )}
      </div>
      {secondary.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {secondary.map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 rounded-full border border-[var(--color-accent)]/30 bg-[var(--color-accent)]/5 px-2 py-0.5 text-[10px] text-[var(--color-text-secondary)]"
            >
              {tag}
              <button
                type="button"
                aria-label={`Remove ${tag}`}
                onClick={() => onSecondary(secondary.filter((t) => t !== tag))}
                className="text-[var(--color-text-muted)] hover:text-[var(--color-error)]"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Renders markdown normally; a click swaps in a textarea whose value is
 * committed on blur (Escape reverts).
 */
export function EditableMarkdown({
  value,
  onCommit,
  placeholder,
  size = 'lg',
  rows = 3,
}: {
  value: string;
  onCommit: (value: string) => void;
  placeholder: string;
  size?: 'sm' | 'lg';
  rows?: number;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const baseline = useRef(value);
  const [syncedFrom, setSyncedFrom] = useState(value);

  // Adjust state during render when the prop changes and we are not editing.
  if (!editing && value !== syncedFrom) {
    setSyncedFrom(value);
    setDraft(value);
  }

  const begin = () => {
    baseline.current = value;
    setDraft(value);
    setEditing(true);
  };
  const commit = () => {
    setEditing(false);
    if (draft !== baseline.current) onCommit(draft);
  };
  const cancel = () => {
    setDraft(baseline.current);
    setEditing(false);
  };

  if (editing) {
    return (
      <textarea
        autoFocus
        value={draft}
        rows={rows}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.preventDefault();
            cancel();
          } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            commit();
          }
        }}
        placeholder={placeholder}
        className="w-full resize-y rounded-lg border border-[var(--color-accent)]/60 bg-[var(--color-bg-primary)] px-3 py-2 text-[17px] leading-7 text-[var(--color-text-primary)] outline-none"
      />
    );
  }
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={begin}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          begin();
        }
      }}
      className="block w-full cursor-text rounded text-left outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-accent)]"
    >
      {value.trim() ? (
        <Markdown text={value} size={size} />
      ) : (
        <span className="text-[17px] leading-7 text-[var(--color-text-muted)]">{placeholder}</span>
      )}
    </div>
  );
}

/** Single-line text input that commits on blur/Enter and reverts on Escape. */
export function EditableText({
  value,
  onCommit,
  placeholder,
  ariaLabel,
  className = inputCls,
  mono = false,
}: {
  value: string;
  onCommit: (value: string) => void;
  placeholder?: string;
  ariaLabel?: string;
  className?: string;
  mono?: boolean;
}) {
  const [draft, setDraft] = useState(value);
  const focused = useRef(false);
  const skip = useRef(false);

  useEffect(() => {
    if (!focused.current) setDraft(value);
  }, [value]);

  return (
    <input
      value={draft}
      aria-label={ariaLabel}
      placeholder={placeholder}
      onFocus={() => {
        focused.current = true;
        setDraft(value);
      }}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        focused.current = false;
        if (skip.current) {
          skip.current = false;
          return;
        }
        if (draft !== value) onCommit(draft);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.currentTarget.blur();
        } else if (e.key === 'Escape') {
          skip.current = true;
          setDraft(value);
          e.currentTarget.blur();
        }
      }}
      className={`${className}${mono ? ' font-mono' : ''}`}
    />
  );
}

/**
 * Textarea that shows plain text (matching the learner's step prompt) and
 * swaps to an editable textarea on click, committing on blur.
 */
export function EditableTextarea({
  value,
  onCommit,
  placeholder,
  rows = 2,
  className = '',
}: {
  value: string;
  onCommit: (value: string) => void;
  placeholder: string;
  rows?: number;
  className?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const baseline = useRef(value);
  const [syncedFrom, setSyncedFrom] = useState(value);

  // Adjust state during render when the prop changes and we are not editing.
  if (!editing && value !== syncedFrom) {
    setSyncedFrom(value);
    setDraft(value);
  }

  const begin = () => {
    baseline.current = value;
    setDraft(value);
    setEditing(true);
  };
  const commit = () => {
    setEditing(false);
    if (draft !== baseline.current) onCommit(draft);
  };
  const cancel = () => {
    setDraft(baseline.current);
    setEditing(false);
  };

  if (editing) {
    return (
      <textarea
        autoFocus
        value={draft}
        rows={rows}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.preventDefault();
            cancel();
          }
        }}
        placeholder={placeholder}
        className={`w-full resize-y rounded-lg border border-[var(--color-accent)]/60 bg-[var(--color-bg-primary)] px-2 py-1 text-[15px] leading-6 text-[var(--color-text-primary)] outline-none ${className}`}
      />
    );
  }
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={begin}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          begin();
        }
      }}
      className="block w-full cursor-text rounded text-left outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-accent)]"
    >
      {value.trim() ? (
        <span className="text-[15px] leading-6 text-[var(--color-text-secondary)]">{value}</span>
      ) : (
        <span className="text-[15px] leading-6 text-[var(--color-text-muted)]">{placeholder}</span>
      )}
    </div>
  );
}

/** Integer input clamped to `[min, max]`, committing on blur/Enter. */
export function EditableNumber({
  value,
  onCommit,
  min = 1,
  max = 100,
  ariaLabel,
  placeholder,
  className = inputCls,
}: {
  value: number;
  onCommit: (value: number) => void;
  min?: number;
  max?: number;
  ariaLabel?: string;
  placeholder?: string;
  className?: string;
}) {
  const [draft, setDraft] = useState(String(value));
  const focused = useRef(false);
  const skip = useRef(false);

  useEffect(() => {
    if (!focused.current) setDraft(String(value));
  }, [value]);

  const commit = () => {
    const n = Number(draft);
    if (draft.trim() === '' || Number.isNaN(n)) {
      setDraft(String(value));
      return;
    }
    const clamped = Math.max(min, Math.min(max, Math.round(n)));
    setDraft(String(clamped));
    if (clamped !== value) onCommit(clamped);
  };

  return (
    <input
      inputMode="numeric"
      value={draft}
      aria-label={ariaLabel}
      placeholder={placeholder}
      onFocus={() => {
        focused.current = true;
        setDraft(String(value));
      }}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        focused.current = false;
        if (skip.current) {
          skip.current = false;
          return;
        }
        commit();
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.currentTarget.blur();
        } else if (e.key === 'Escape') {
          skip.current = true;
          setDraft(String(value));
          e.currentTarget.blur();
        }
      }}
      className={className}
    />
  );
}
