import { useEffect, useRef, useState } from 'react';
import type { AdminTaxonomy } from '../../api/client';
import { Markdown } from '../Markdown/Markdown';

const inputCls =
  'w-full rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] px-2 py-1.5 text-xs text-[var(--color-text-primary)]';
const labelCls = 'mb-0.5 block text-xs text-[var(--color-text-muted)]';

/** Grouped taxonomy options (`domain / area` optgroups), optionally filtered. */
export function TaxonomyOptions({
  taxonomy,
  exclude = [],
}: {
  taxonomy: AdminTaxonomy;
  exclude?: string[];
}) {
  return (
    <>
      {taxonomy.domains.map((domain) =>
        Object.entries(taxonomy.tree[domain] ?? {}).map(([area, skills]) => {
          const visible = skills.filter((s) => !exclude.includes(s));
          if (visible.length === 0) return null;
          return (
            <optgroup key={`${domain}/${area}`} label={`${domain} / ${area}`}>
              {visible.map((tag) => (
                <option key={tag} value={tag}>
                  {tag}
                </option>
              ))}
            </optgroup>
          );
        }),
      )}
    </>
  );
}

function TagSelect({
  taxonomy,
  value,
  onChange,
  exclude,
}: {
  taxonomy: AdminTaxonomy;
  value: string;
  onChange: (tag: string) => void;
  exclude?: string[];
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={inputCls}>
      {value === '' && <option value="">Select a skill…</option>}
      <TaxonomyOptions taxonomy={taxonomy} exclude={exclude} />
    </select>
  );
}

/**
 * Primary + up to two secondary tag picker. Primary is a grouped select;
 * secondaries render as removable chips with an "add" select.
 */
export function TagEditor({
  taxonomy,
  primary,
  secondary,
  onPrimary,
  onSecondary,
  primaryLabel = 'primary tag *',
}: {
  taxonomy: AdminTaxonomy;
  primary: string;
  secondary: string[];
  onPrimary: (tag: string) => void;
  onSecondary: (tags: string[]) => void;
  primaryLabel?: string;
}) {
  const chosen = [primary, ...secondary].filter(Boolean);
  return (
    <div className="space-y-1.5">
      <label className="block">
        <span className={labelCls}>{primaryLabel}</span>
        <TagSelect taxonomy={taxonomy} value={primary} onChange={onPrimary} exclude={secondary} />
      </label>
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
      {secondary.length < 2 && (
        <select
          value=""
          onChange={(e) => {
            if (e.target.value) onSecondary([...secondary, e.target.value]);
          }}
          className={`${inputCls} text-[var(--color-text-muted)]`}
        >
          <option value="">+ add secondary tag (optional)…</option>
          <TaxonomyOptions taxonomy={taxonomy} exclude={chosen} />
        </select>
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
