import { useEffect, useState } from 'react';
import { apiClient, type AdminSeedCreate, type AdminTaxonomy } from '../../api/client';

interface HintDraft {
  id: string;
  text: string;
  weight: string;
  reveal_threshold: string;
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
  const [clusterId, setClusterId] = useState('');
  const [hints, setHints] = useState<HintDraft[]>([]);
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

  const updateHint = (idx: number, patch: Partial<HintDraft>) => {
    setHints((prev) => prev.map((h, i) => (i === idx ? { ...h, ...patch } : h)));
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
    setSaving(true);
    try {
      const body: AdminSeedCreate = {
        prompt: prompt.trim(),
        scaffold: scaffold.trim() || undefined,
        difficulty,
        max_score: maxScore,
        hints: hints
          .filter((h) => h.text.trim())
          .map((h) => ({
            id: h.id.trim() || `hint_${Math.random().toString(36).slice(2, 8)}`,
            text: h.text.trim(),
            weight: clamp01(Number(h.weight) || 0),
            reveal_threshold: clamp01(Number(h.reveal_threshold) || 0),
          })),
        tags: { primary, secondary },
        task_type: taskType,
        context_notes: contextNotes.trim() || undefined,
        cluster_id: clusterId.trim() || undefined,
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
            placeholder="Describe the task in plain English…"
            className={inputCls}
          />
        </label>

        <label className="block">
          <span className={labelCls}>scaffold (starter code)</span>
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
          <select value={primary} onChange={(e) => setPrimary(e.target.value)} className={inputCls}>
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
          <span className={labelCls}>hints (optional)</span>
          {hints.map((h, i) => (
            <div key={i} className="mb-2 rounded-lg border border-[var(--color-border-default)] p-2">
              <div className="grid grid-cols-2 gap-1.5">
                <input
                  value={h.id}
                  onChange={(e) => updateHint(i, { id: e.target.value })}
                  placeholder="id"
                  className={inputCls}
                />
                <input
                  value={h.weight}
                  onChange={(e) => updateHint(i, { weight: e.target.value })}
                  placeholder="weight 0..1"
                  className={inputCls}
                />
              </div>
              <textarea
                value={h.text}
                onChange={(e) => updateHint(i, { text: e.target.value })}
                rows={2}
                placeholder="Hint text"
                className={`${inputCls} mt-1.5`}
              />
              <div className="mt-1.5 flex items-center gap-1.5">
                <input
                  value={h.reveal_threshold}
                  onChange={(e) => updateHint(i, { reveal_threshold: e.target.value })}
                  placeholder="reveal_threshold 0..1"
                  className={inputCls}
                />
                <button
                  type="button"
                  onClick={() => setHints((prev) => prev.filter((_, j) => j !== i))}
                  className="shrink-0 rounded-lg border border-[var(--color-error)]/40 px-2 py-1.5 text-xs text-[var(--color-error)]"
                >
                  Remove
                </button>
              </div>
            </div>
          ))}
          <button
            type="button"
            onClick={() =>
              setHints((prev) => [
                ...prev,
                { id: '', text: '', weight: '0.15', reveal_threshold: '0.5' },
              ])
            }
            className="rounded-lg border border-[var(--color-border-default)] px-2 py-1.5 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
          >
            + Add hint
          </button>
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

        <label className="block">
          <span className={labelCls}>cluster_id (optional)</span>
          <input
            value={clusterId}
            onChange={(e) => setClusterId(e.target.value)}
            placeholder="Thematic thread, e.g. dl_architectures"
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

function clamp01(n: number): number {
  if (Number.isNaN(n)) return 0;
  return Math.max(0, Math.min(1, n));
}