import { useEffect, useState } from 'react';
import {
  apiClient,
  type Taxonomy,
  type CuratorTask,
  type TaskCreateBody,
  type TaskPart,
} from '../../api/client';
import { scaffoldHygieneIssues } from '../../lib/task-hygiene';
import { CodeEditor } from '../TaskPanel/CodeEditor';
import { QuestionBubble } from '../Task/QuestionBubble';
import {
  EditableMarkdown,
  EditableNumber,
  EditableText,
  TagEditor,
} from './Editable';

interface PartDraft {
  key: string;
  prompt: string;
  scaffold: string;
  max_score: string;
  difficulty: string;
  pass_score: string;
  primary: string;
  secondary: string[];
}

interface Props {
  task: CuratorTask | null;
  onSaved: (task: CuratorTask) => void;
  onDeleted: (taskId: string) => void;
  onClose: () => void;
  onError: (msg: string) => void;
}

const LANGUAGES = ['python', 'cpp', 'c', 'javascript', 'typescript', 'java', 'go', 'rust'];

const labelCls = 'mb-0.5 block text-[10px] text-[var(--color-text-muted)]';
const fieldCls =
  'w-full rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] px-2 py-1 text-xs text-[var(--color-text-primary)]';

function blankPart(primary = ''): PartDraft {
  return {
    key: '',
    prompt: '',
    scaffold: '',
    max_score: '5',
    difficulty: '2',
    pass_score: '',
    primary,
    secondary: [],
  };
}

function partsToDrafts(parts?: TaskPart[]): PartDraft[] {
  return (parts ?? []).map((p) => ({
    key: p.key,
    prompt: p.prompt,
    scaffold: p.scaffold ?? '',
    max_score: String(p.max_score ?? 5),
    difficulty: String(p.difficulty ?? 2),
    pass_score: p.pass_score != null ? String(p.pass_score) : '',
    primary: p.tags?.primary ?? '',
    secondary: p.tags?.secondary ?? [],
  }));
}

/** Mirrors the backend's `default_pass_score` (round(0.7 * max), min 1). */
function autoPassScore(maxScore: number): number {
  return Math.max(1, Math.round(0.7 * Math.max(1, maxScore)));
}

/**
 * Merged curator editor: a single learner-style column. The question bubble
 * renders exactly as a candidate sees it (the active step's markdown prompt,
 * tag chips, starter code) with the editable fields inline, plus curator-only
 * settings/step-detail panels marked "hidden from learners". There is no
 * overview field — the task-level prompt is derived from the first step.
 */
export function TaskEditor({ task, onSaved, onDeleted, onClose, onError }: Props) {
  const [taxonomy, setTaxonomy] = useState<Taxonomy | null>(null);
  const [language, setLanguage] = useState(task?.language ?? 'python');
  const [taskType, setTaskType] = useState(task?.task_type ?? 'implement');
  const [isPublic, setIsPublic] = useState(task ? task.is_public : true);
  const [parts, setParts] = useState<PartDraft[]>(() => {
    const drafts = partsToDrafts(task?.parts);
    return drafts.length > 0 ? drafts : [blankPart()];
  });
  const [activeStep, setActiveStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    apiClient
      .taxonomy()
      .then(setTaxonomy)
      .catch((e) => onError(e instanceof Error ? e.message : String(e)));
  }, [onError]);

  const updatePart = (idx: number, patch: Partial<PartDraft>) => {
    setParts((prev) => prev.map((p, i) => (i === idx ? { ...p, ...patch } : p)));
  };

  const addStep = () => {
    setParts((prev) => [...prev, blankPart(prev[activeStep]?.primary ?? '')]);
    setActiveStep(parts.length);
  };

  const removeStep = (idx: number) => {
    if (parts.length <= 1) return;
    const newLen = parts.length - 1;
    setParts((prev) => prev.filter((_, i) => i !== idx));
    setActiveStep((cur) => {
      const shifted = cur > idx ? cur - 1 : cur;
      return Math.max(0, Math.min(shifted, newLen - 1));
    });
  };

  const moveStep = (idx: number, dir: -1 | 1) => {
    const to = idx + dir;
    if (to < 0 || to >= parts.length) return;
    setParts((prev) => {
      const next = [...prev];
      [next[idx], next[to]] = [next[to], next[idx]];
      return next;
    });
    setActiveStep(to);
  };

  /** Validate + build the create/update body; returns null on invalid input. */
  const buildBody = (): TaskCreateBody | null => {
    setFormError(null);
    const cleaned: TaskPart[] = [];
    const seen = new Set<string>();
    for (const p of parts) {
      const hasKey = p.key.trim().length > 0;
      const hasPrompt = p.prompt.trim().length > 0;
      if (!hasKey && !hasPrompt) continue;
      if (!hasKey || !hasPrompt) {
        const msg = 'Every step needs both a key and a prompt.';
        setFormError(msg);
        onError(msg);
        return null;
      }
      if (seen.has(p.key.trim())) {
        const msg = `Duplicate step key: ${p.key.trim()}`;
        setFormError(msg);
        onError(msg);
        return null;
      }
      if (!p.primary) {
        const msg = `Step ${p.key.trim()} needs a primary skill.`;
        setFormError(msg);
        onError(msg);
        return null;
      }
      seen.add(p.key.trim());
      const part: TaskPart = {
        key: p.key.trim(),
        prompt: p.prompt.trim(),
        max_score: clamp1to100(Number(p.max_score)) || 5,
        difficulty: clamp1to5(Number(p.difficulty)) || 2,
        tags: { primary: p.primary, secondary: p.secondary.slice(0, 2) },
      };
      if (p.scaffold.trim()) part.scaffold = p.scaffold;
      if (p.pass_score.trim() !== '') {
        part.pass_score = Math.max(0, Math.min(part.max_score, Number(p.pass_score) || 0));
      }
      cleaned.push(part);
    }
    if (cleaned.length === 0) {
      const msg = 'Every step needs both a key and a prompt.';
      setFormError(msg);
      onError(msg);
      return null;
    }
    const body: TaskCreateBody = {
      parts: cleaned,
      task_type: taskType,
      language,
      is_public: isPublic,
    };
    return body;
  };

  const submit = async () => {
    const body = buildBody();
    if (!body) return;
    setSaving(true);
    try {
      const saved = task
        ? await apiClient.updateTask(task.id, body)
        : await apiClient.createTask(body);
      onSaved(saved as CuratorTask);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setFormError(msg);
      onError(msg);
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!task) return;
    const cascade = task.attempt_count
      ? `\nThis will also delete ${task.attempt_count} recorded attempt(s).`
      : '';
    const title = task.prompt.trim().slice(0, 60) || 'this question';
    if (!window.confirm(`Delete “${title}”?${cascade}\nThis cannot be undone.`)) return;
    try {
      await apiClient.deleteTask(task.id);
      onDeleted(task.id);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  if (!taxonomy) {
    return (
      <div className="flex h-full flex-1 items-center justify-center p-4">
        <p className="text-xs text-[var(--color-text-muted)]">Loading question form…</p>
      </div>
    );
  }

  const active = parts[activeStep] ?? parts[0];
  const activeMax = clamp1to100(Number(active.max_score)) || 5;
  const passScoreValue =
    active.pass_score.trim() !== ''
      ? Math.max(0, Math.min(activeMax, Number(active.pass_score) || 0))
      : autoPassScore(activeMax);
  const activeScaffoldIssues = scaffoldHygieneIssues(active.scaffold);

  const activeTaskPart: TaskPart = {
    key: active.key.trim() || `step_${activeStep + 1}`,
    prompt: active.prompt,
    max_score: activeMax,
    difficulty: clamp1to5(Number(active.difficulty)) || 2,
    tags: { primary: active.primary, secondary: active.secondary },
  };

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl space-y-3 px-4 py-4 lg:max-w-4xl">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-sm font-semibold text-[var(--color-text-primary)]">
              {task ? 'Edit question' : 'New question'}
            </h3>
            {task && (
              <span className="text-[11px] text-[var(--color-text-muted)]">
                {task.attempt_count ?? 0} attempts
              </span>
            )}
          </div>

          {/* Curator-only settings. */}
          <section className="space-y-2 rounded-xl border border-dashed border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-2.5">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
              Question settings — hidden from learners
            </p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <label className="block">
                <span className={labelCls}>language</span>
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  className={fieldCls}
                >
                  {LANGUAGES.map((l) => (
                    <option key={l} value={l}>
                      {l}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className={labelCls}>task type</span>
                <select
                  value={taskType}
                  onChange={(e) => setTaskType(e.target.value)}
                  className={fieldCls}
                >
                  {taxonomy.task_types.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </label>
              <label className="col-span-2 flex items-center gap-2 self-end pb-1">
                <input
                  type="checkbox"
                  checked={isPublic}
                  onChange={(e) => setIsPublic(e.target.checked)}
                  className="h-3.5 w-3.5"
                />
                <span className="text-[11px] text-[var(--color-text-secondary)]">
                  Public in the question bank (visible to all learners)
                </span>
              </label>
            </div>
          </section>

          {/* Step tabs mirror the learner advancing one step at a time. */}
          <div className="flex flex-wrap items-center gap-1.5">
            {parts.map((_p, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setActiveStep(i)}
                className={`rounded-lg border px-2.5 py-1 text-[11px] transition-colors ${
                  i === activeStep
                    ? 'border-[var(--color-accent)]/50 bg-[var(--color-accent)]/10 text-[var(--color-accent)]'
                    : 'border-[var(--color-border-default)] text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]'
                }`}
              >
                Step {i + 1}
              </button>
            ))}
            <button
              type="button"
              onClick={addStep}
              className="rounded-lg border border-[var(--color-border-default)] px-2.5 py-1 text-[11px] text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
            >
              + Add step
            </button>
          </div>

          {/* Learner-style question bubble, editable in place. */}
          <QuestionBubble
            parts={[activeTaskPart]}
            phaseIndex={activeStep + 1}
            phaseTotal={parts.length}
            renderPrompt={(p) => (
              <EditableMarkdown
                value={p}
                onCommit={(v) => updatePart(activeStep, { prompt: v })}
                placeholder="What should the learner do in this step?"
              />
            )}
          />

          {/* Curator-only step details. */}
          <section className="space-y-2 rounded-xl border border-dashed border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-2.5">
            <div className="flex items-center gap-2">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                Step {activeStep + 1} details — hidden from learners
              </p>
              <div className="ml-auto flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => moveStep(activeStep, -1)}
                  disabled={activeStep === 0}
                  aria-label="Move step up"
                  title="Move step up"
                  className="rounded-md border border-[var(--color-border-default)] px-1.5 py-0.5 text-[11px] leading-4 disabled:opacity-30"
                >
                  ↑
                </button>
                <button
                  type="button"
                  onClick={() => moveStep(activeStep, 1)}
                  disabled={activeStep === parts.length - 1}
                  aria-label="Move step down"
                  title="Move step down"
                  className="rounded-md border border-[var(--color-border-default)] px-1.5 py-0.5 text-[11px] leading-4 disabled:opacity-30"
                >
                  ↓
                </button>
                <button
                  type="button"
                  onClick={() => removeStep(activeStep)}
                  disabled={parts.length <= 1}
                  className="rounded-md border border-[var(--color-error)]/40 px-1.5 py-0.5 text-[11px] leading-4 text-[var(--color-error)] disabled:opacity-30"
                >
                  Remove
                </button>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-6">
              <label className="col-span-2 block sm:col-span-3">
                <span className={labelCls}>step key (internal)</span>
                <EditableText
                  value={active.key}
                  onCommit={(v) => updatePart(activeStep, { key: v })}
                  placeholder="step_key"
                  ariaLabel="Step key"
                  mono
                  className={fieldCls}
                />
              </label>
              <label className="block">
                <span className={labelCls}>max_score</span>
                <EditableNumber
                  value={activeMax}
                  min={1}
                  max={100}
                  onCommit={(v) => updatePart(activeStep, { max_score: String(v) })}
                  ariaLabel="Max score"
                  className={fieldCls}
                />
              </label>
              <label className="block">
                <span className={labelCls}>difficulty</span>
                <EditableNumber
                  value={clamp1to5(Number(active.difficulty)) || 2}
                  min={1}
                  max={5}
                  onCommit={(v) => updatePart(activeStep, { difficulty: String(v) })}
                  ariaLabel="Difficulty"
                  className={fieldCls}
                />
              </label>
              <label className="block">
                <span className={labelCls}>pass_score</span>
                <EditableNumber
                  value={passScoreValue}
                  min={0}
                  max={activeMax}
                  onCommit={(v) => updatePart(activeStep, { pass_score: String(v) })}
                  ariaLabel="Pass score"
                  className={fieldCls}
                />
              </label>
            </div>
            <TagEditor
              taxonomy={taxonomy}
              primary={active.primary}
              secondary={active.secondary}
              onPrimary={(t) => updatePart(activeStep, { primary: t })}
              onSecondary={(tags) => updatePart(activeStep, { secondary: tags })}
              primaryLabel="step primary *"
            />
          </section>

          {/* Starter code for the active step. */}
          <div>
            <p className={labelCls}>Starter code for this step (optional)</p>
            <CodeEditor
              key={`${task?.id ?? 'new'}:${activeStep}`}
              code={active.scaffold}
              language={language}
              onChange={(v) => updatePart(activeStep, { scaffold: v })}
              height="h-56"
            />
            {activeScaffoldIssues.length > 0 && (
              <p className="mt-1.5 rounded-lg border border-[var(--color-warning,#b45309)]/30 bg-[var(--color-bg-secondary)] px-3 py-1.5 text-[11px] text-[var(--color-text-secondary)]">
                Starter-code check: exposes {activeScaffoldIssues.join('; ')}. Comment the API
                instead — learners are evaluated on the design too.
              </p>
            )}
          </div>

          {formError && (
            <p className="rounded-lg border border-[var(--color-error)]/30 bg-[var(--color-bg-secondary)] px-3 py-1.5 text-xs text-[var(--color-error)]">
              {formError}
            </p>
          )}

          <div className="sticky bottom-0 -mx-4 flex flex-wrap gap-2 border-t border-[var(--color-border-default)] bg-[var(--color-bg-primary)] px-4 py-3">
            <button
              onClick={() => void submit()}
              disabled={saving}
              className="rounded-lg bg-[var(--color-accent)] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
            >
              {saving ? 'Saving…' : task ? 'Save changes' : 'Create question'}
            </button>
            <button
              onClick={onClose}
              className="rounded-lg border border-[var(--color-border-default)] px-3 py-1.5 text-xs"
            >
              Cancel
            </button>
            {task && (
              <button
                onClick={() => void remove()}
                className="ml-auto rounded-lg border border-[var(--color-error)]/40 px-3 py-1.5 text-xs text-[var(--color-error)]"
              >
                Delete
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function clamp1to5(n: number): number {
  if (Number.isNaN(n)) return 0;
  return Math.max(1, Math.min(5, Math.round(n)));
}

function clamp1to100(n: number): number {
  if (Number.isNaN(n)) return 0;
  return Math.max(1, Math.min(100, Math.round(n)));
}
