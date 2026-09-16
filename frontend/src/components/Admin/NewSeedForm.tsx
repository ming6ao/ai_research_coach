import { useEffect, useState } from 'react';
import { apiClient, type AdminSeedCreate, type AdminTaxonomy, type TaskPart } from '../../api/client';

interface PartDraft {
  key: string;
  prompt: string;
  max_score: string;
  difficulty: string;
  primary: string;
  secondary: string[];
}

interface Props {
  onCreated: (taskId: string) => void;
  onClose: () => void;
  onError: (msg: string) => void;
}

const TASK_TYPES = ['implement', 'apply', 'debug', 'design', 'analyze'];

const inputCls =
  'w-full rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] px-2 py-1.5 text-xs text-[var(--color-text-primary)]';
const labelCls = 'mb-0.5 block text-xs text-[var(--color-text-muted)]';

function blankPart(): PartDraft {
  return { key: '', prompt: '', max_score: '5', difficulty: '2', primary: 'python', secondary: [] };
}

export function NewSeedForm({ onCreated, onClose, onError }: Props) {
  const [taxonomy, setTaxonomy] = useState<AdminTaxonomy | null>(null);
  const [prompt, setPrompt] = useState('');
  const [scaffold, setScaffold] = useState('');
  const [difficulty, setDifficulty] = useState(2);
  const [maxScore, setMaxScore] = useState(5);
  const [taskType, setTaskType] = useState('implement');
  const [primary, setPrimary] = useState('python');
  const [secondary, setSecondary] = useState<string[]>([]);
  const [contextNotes, setContextNotes] = useState('');
  const [parts, setParts] = useState<PartDraft[]>([]);
  const [versionIndex, setVersionIndex] = useState('');
  const [dependsOn, setDependsOn] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiClient
      .adminTaxonomy()
      .then((t) => {
        setTaxonomy(t);
        const firstTag = t.tags[t.families[0] ?? '']?.[0];
        if (firstTag) setPrimary(firstTag);
      })
      .catch((e) => onError(e instanceof Error ? e.message : String(e)));
  }, [onError]);

  const allTags = taxonomy
    ? taxonomy.families.flatMap((fam) => (taxonomy.tags[fam] ?? []).map((tag) => ({ tag, fam })))
    : [];

  const toggleSecondary = (tag: string) => {
    if (tag === primary) return;
    setSecondary((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : prev.length >= 2 ? prev : [...prev, tag],
    );
  };

  const updatePart = (idx: number, patch: Partial<PartDraft>) => {
    setParts((prev) => prev.map((p, i) => (i === idx ? { ...p, ...patch } : p)));
  };

  const togglePartSecondary = (idx: number, tag: string) => {
    setParts((prev) =>
      prev.map((p, i) => {
        if (i !== idx) return p;
        if (tag === p.primary) return p;
        const next = p.secondary.includes(tag)
          ? p.secondary.filter((t) => t !== tag)
          : p.secondary.length >= 2
            ? p.secondary
            : [...p.secondary, tag];
        return { ...p, secondary: next };
      }),
    );
  };

  const submit = async () => {
    if (!prompt.trim()) {
      onError('Prompt must not be empty.');
      return;
    }
    if (!primary) {
      onError('Select a primary tag.');
      return;
    }
    const cleaned: TaskPart[] = [];
    const seen = new Set<string>();
    for (const p of parts) {
      if (!p.key.trim() || !p.prompt.trim()) continue;
      if (seen.has(p.key.trim())) {
        onError(`Duplicate part key: ${p.key.trim()}`);
        return;
      }
      seen.add(p.key.trim());
      cleaned.push({
        key: p.key.trim(),
        prompt: p.prompt.trim(),
        max_score: clamp01to100(Number(p.max_score)) || 5,
        difficulty: clamp15(Number(p.difficulty)) || 2,
        tags: { primary: p.primary, secondary: p.secondary },
      });
    }
    setSaving(true);
    try {
      const body: AdminSeedCreate = {
        prompt: prompt.trim(),
        scaffold: scaffold.trim() || undefined,
        difficulty,
        max_score: maxScore,
        parts: cleaned.length ? cleaned : undefined,
        tags: { primary, secondary },
        task_type: taskType,
        context_notes: contextNotes.trim() || undefined,
        version_index: versionIndex ? Math.max(1, Number(versionIndex)) : undefined,
        depends_on_task_id: dependsOn.trim() || undefined,
      };
      const task = await apiClient.adminCreateSeed(body);
      onCreated(task.id);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  if (!taxonomy) {
    return (
      <div className="flex h-full items-center justify-center p-4">
        <p className="text-xs text-[var(--color-text-muted)]">Loading question form…</p>
      </div>
    );
  }

  const renderTagPicker = (
    value: string,
    onChange: (t: string) => void,
  ) => (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={inputCls}>
      {taxonomy.families.map((fam) => (
        <optgroup key={fam} label={fam}>
          {(taxonomy.tags[fam] ?? []).map((tag) => (
            <option key={tag} value={tag}>
              {tag}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );

  return (
    <div className="w-96 shrink-0 overflow-y-auto border-l border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          New seed question
        </h3>
        <button
          onClick={onClose}
          className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
        >
          ×
        </button>
      </div>

      <div className="space-y-3">
        <label className="block">
          <span className={labelCls}>prompt *</span>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={5}
            placeholder="Describe the block in plain English…"
            className={inputCls}
          />
        </label>

        <label className="block">
          <span className={labelCls}>scaffold (starter code covering all parts)</span>
          <textarea
            value={scaffold}
            onChange={(e) => setScaffold(e.target.value)}
            rows={5}
            placeholder="def solve(...):\n    # TODO"
            className={`${inputCls} font-mono`}
          />
        </label>

        <div className="grid grid-cols-2 gap-2">
          <label className="block">
            <span className={labelCls}>difficulty</span>
            <select
              value={difficulty}
              onChange={(e) => setDifficulty(Number(e.target.value))}
              className={inputCls}
            >
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className={labelCls}>max_score</span>
            <input
              type="number"
              min={1}
              max={100}
              value={maxScore}
              onChange={(e) => setMaxScore(Number(e.target.value))}
              className={inputCls}
            />
          </label>
        </div>

        <label className="block">
          <span className={labelCls}>task_type</span>
          <select value={taskType} onChange={(e) => setTaskType(e.target.value)} className={inputCls}>
            {TASK_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className={labelCls}>primary tag *</span>
          {renderTagPicker(primary, setPrimary)}
        </label>

        <div>
          <span className={labelCls}>secondary tags (0–2)</span>
          <div className="max-h-40 overflow-y-auto rounded-lg border border-[var(--color-border-default)] p-2">
            {allTags
              .filter((t) => t.tag !== primary)
              .sort((a, b) => a.fam.localeCompare(b.fam) || a.tag.localeCompare(b.tag))
              .map(({ tag, fam }) => {
                const active = secondary.includes(tag);
                const disabled = !active && secondary.length >= 2;
                return (
                  <button
                    key={tag}
                    type="button"
                    disabled={disabled}
                    onClick={() => toggleSecondary(tag)}
                    className={`mb-0.5 mr-1 inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] ${
                      active
                        ? 'border-[var(--color-accent)]/40 bg-[var(--color-accent)]/10 text-[var(--color-text-primary)]'
                        : 'border-[var(--color-border-default)] text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]'
                    } ${disabled ? 'opacity-40' : ''}`}
                    title={fam}
                  >
                    {tag}
                  </button>
                );
              })}
          </div>
        </div>

        <div>
          <span className={labelCls}>parts (code block; optional)</span>
          {parts.map((p, i) => (
            <div key={i} className="mb-2 rounded-lg border border-[var(--color-border-default)] p-2">
              <div className="grid grid-cols-3 gap-1.5">
                <input
                  value={p.key}
                  onChange={(e) => updatePart(i, { key: e.target.value })}
                  placeholder="key, e.g. softmax"
                  className={inputCls}
                />
                <input
                  value={p.max_score}
                  onChange={(e) => updatePart(i, { max_score: e.target.value })}
                  placeholder="max_score"
                  className={inputCls}
                />
                <input
                  value={p.difficulty}
                  onChange={(e) => updatePart(i, { difficulty: e.target.value })}
                  placeholder="difficulty 1..5"
                  className={inputCls}
                />
              </div>
              <textarea
                value={p.prompt}
                onChange={(e) => updatePart(i, { prompt: e.target.value })}
                rows={2}
                placeholder="Part prompt (self-contained)"
                className={`${inputCls} mt-1.5`}
              />
              <div className="mt-1.5">
                {renderTagPicker(p.primary, (t) => updatePart(i, { primary: t, secondary: [] }))}
              </div>
              <div className="mt-1.5">
                {allTags
                  .filter((t) => t.tag !== p.primary)
                  .slice(0, 24)
                  .map(({ tag, fam }) => {
                    const active = p.secondary.includes(tag);
                    const disabled = !active && p.secondary.length >= 2;
                    return (
                      <button
                        key={tag}
                        type="button"
                        disabled={disabled}
                        onClick={() => togglePartSecondary(i, tag)}
                        className={`mb-0.5 mr-1 inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] ${
                          active
                            ? 'border-[var(--color-accent)]/40 bg-[var(--color-accent)]/10 text-[var(--color-text-primary)]'
                            : 'border-[var(--color-border-default)] text-[var(--color-text-muted)]'
                        } ${disabled ? 'opacity-40' : ''}`}
                        title={fam}
                      >
                        {tag}
                      </button>
                    );
                  })}
              </div>
              <button
                type="button"
                onClick={() => setParts((prev) => prev.filter((_, j) => j !== i))}
                className="mt-1.5 rounded-lg border border-[var(--color-error)]/40 px-2 py-1 text-xs text-[var(--color-error)]"
              >
                Remove part
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={() => setParts((prev) => [...prev, blankPart()])}
            className="rounded-lg border border-[var(--color-border-default)] px-2 py-1.5 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
          >
            + Add part
          </button>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <label className="block">
            <span className={labelCls}>version_index (optional)</span>
            <input
              type="number"
              min={1}
              value={versionIndex}
              onChange={(e) => setVersionIndex(e.target.value)}
              placeholder="2 for a successor"
              className={inputCls}
            />
          </label>
          <label className="block">
            <span className={labelCls}>depends_on_task_id (optional)</span>
            <input
              value={dependsOn}
              onChange={(e) => setDependsOn(e.target.value)}
              placeholder="seed_transformer_decode"
              className={inputCls}
            />
          </label>
        </div>

        <label className="block">
          <span className={labelCls}>context_notes (optional)</span>
          <textarea
            value={contextNotes}
            onChange={(e) => setContextNotes(e.target.value)}
            rows={3}
            placeholder="Leave blank to auto-generate via LLM."
            className={inputCls}
          />
        </label>

        <div className="flex gap-2 pt-1">
          <button
            onClick={() => void submit()}
            disabled={saving}
            className="rounded-lg bg-[var(--color-accent)] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
          >
            {saving ? 'Saving…' : 'Create seed'}
          </button>
          <button
            onClick={onClose}
            className="rounded-lg border border-[var(--color-border-default)] px-3 py-1.5 text-xs"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function clamp15(n: number): number {
  if (Number.isNaN(n)) return 0;
  return Math.max(1, Math.min(5, Math.round(n)));
}

function clamp01to100(n: number): number {
  if (Number.isNaN(n)) return 0;
  return Math.max(1, Math.min(100, Math.round(n)));
}