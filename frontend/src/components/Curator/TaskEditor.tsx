import { useEffect, useState } from 'react';
import {
  apiClient,
  type Taxonomy,
  type CuratorTask,
  type TaskCreateBody,
  type TaskPart,
} from '../../api/client';
import { scaffoldHygieneIssues } from '../../lib/task-hygiene';
import { findStepDraftError, splitStepPrompts } from '../../lib/task-draft';
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
  /** Starter code per language; the first declared language is the default. */
  scaffolds: Record<string, string>;
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
    scaffolds: {},
    max_score: '5',
    difficulty: '2',
    pass_score: '',
    primary,
    secondary: [],
  };
}

/** The default language is the first declared one (never empty). */
function defaultLanguage(languages: string[]): string {
  return languages[0] ?? 'python';
}

function partsToDrafts(parts: TaskPart[] | undefined, languages: string[]): PartDraft[] {
  return (parts ?? []).map((p) => {
    const scaffolds: Record<string, string> = {};
    for (const lang of languages) {
      const code = p.scaffolds?.[lang] ?? (lang === 'python' ? p.scaffold : undefined);
      if (code) scaffolds[lang] = code;
    }
    return {
      key: p.key,
      prompt: p.prompt,
      scaffolds,
      max_score: String(p.max_score ?? 5),
      difficulty: String(p.difficulty ?? 2),
      pass_score: p.pass_score != null ? String(p.pass_score) : '',
      primary: p.tags?.primary ?? '',
      secondary: p.tags?.secondary ?? [],
    };
  });
}

function draftsToParts(drafts: PartDraft[], languages: string[]): TaskPart[] {
  const defaultLang = defaultLanguage(languages);
  const out: TaskPart[] = [];
  for (const p of drafts) {
    if (!p.prompt.trim()) continue;
    const scaffolds: Record<string, string> = {};
    for (const lang of languages) {
      const code = (p.scaffolds[lang] ?? '').trim();
      if (code) scaffolds[lang] = code;
    }
    const part: TaskPart = {
      key: p.key.trim() || `step_${out.length + 1}`,
      prompt: p.prompt.trim(),
      max_score: clamp1to100(Number(p.max_score)) || 5,
      difficulty: clamp1to5(Number(p.difficulty)) || 2,
      tags: { primary: p.primary, secondary: p.secondary.slice(0, 2) },
    };
    if (scaffolds[defaultLang]) part.scaffold = scaffolds[defaultLang];
    if (languages.length > 1) part.scaffolds = scaffolds;
    if (p.pass_score.trim() !== '') {
      part.pass_score = Math.max(0, Math.min(part.max_score, Number(p.pass_score) || 0));
    }
    out.push(part);
  }
  return out;
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
  const [languages, setLanguages] = useState<string[]>(() =>
    task?.languages?.length ? task.languages : [task?.language ?? 'python'],
  );
  const [scaffoldLang, setScaffoldLang] = useState<string>(
    () => task?.languages?.[0] ?? task?.language ?? 'python',
  );
  const [taskType, setTaskType] = useState(task?.task_type ?? 'implement');
  const [isPublic, setIsPublic] = useState(task ? task.is_public : true);
  const [parts, setParts] = useState<PartDraft[]>(() => {
    const initialLangs = task?.languages?.length
      ? task.languages
      : [task?.language ?? 'python'];
    const drafts = partsToDrafts(task?.parts, initialLangs);
    return drafts.length > 0 ? drafts : [blankPart()];
  });
  const [activeStep, setActiveStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [contextNotes, setContextNotes] = useState(task?.context_notes ?? '');
  const [assistantOpen, setAssistantOpen] = useState(!task);
  const [quickText, setQuickText] = useState('');
  const [quickInstruction, setQuickInstruction] = useState('');
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [assistantError, setAssistantError] = useState<string | null>(null);

  useEffect(() => {
    apiClient
      .taxonomy()
      .then(setTaxonomy)
      .catch((e) => onError(e instanceof Error ? e.message : String(e)));
  }, [onError]);

  const updatePart = (idx: number, patch: Partial<PartDraft>) => {
    setParts((prev) => prev.map((p, i) => (i === idx ? { ...p, ...patch } : p)));
  };

  /** Add/remove a language; the first remains the default and at least one
   * language must stay selected. */
  const toggleLanguage = (lang: string) => {
    const next = languages.includes(lang)
      ? languages.filter((l) => l !== lang)
      : [...languages, lang];
    const stable = next.length > 0 ? next : [lang];
    setLanguages(stable);
    if (!stable.includes(scaffoldLang)) setScaffoldLang(stable[0]);
  };

  /** Persist a curator-typed skill under an existing area, then refresh the
   * vocabulary so it becomes a normal option everywhere in the editor. */
  const addSkill = async (skill: string, area: string): Promise<string> => {
    const created = await apiClient.createSkill({ skill, area });
    const fresh = await apiClient.taxonomy();
    setTaxonomy(fresh);
    return created.skill;
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

  /**
   * Report anything the assistant could not fill in (e.g. a scaffold it
   * omitted or produced invalid). The draft still hydrates the form so the
   * curator keeps the rest, but Create stays blocked until they fix it.
   */
  const reportDraftProblems = (problems?: string[]) => {
    if (!problems || problems.length === 0) return;
    setAssistantError(
      `The AI assistant couldn't fill everything in: ${problems.join('; ')}. ` +
        'Add the missing details by hand.',
    );
  };

  /** Replace the form state with an AI-drafted (or refined) task body. */
  const applyDraft = (draft: TaskCreateBody) => {
    const nextLangs = draft.languages?.length
      ? draft.languages
      : draft.language
        ? [draft.language]
        : languages;
    const next = partsToDrafts(draft.parts, nextLangs);
    setParts(next.length > 0 ? next : [blankPart()]);
    setActiveStep(0);
    setLanguages(nextLangs);
    setScaffoldLang(nextLangs[0]);
    if (draft.task_type) setTaskType(draft.task_type);
    if (draft.context_notes != null) setContextNotes(draft.context_notes);
  };

  /** Initial draft: curator step prompts -> fully-populated form. */
  const generateDraft = async () => {
    setAssistantError(null);
    const steps = splitStepPrompts(quickText);
    if (steps.length === 0) {
      setAssistantError('Enter at least one step prompt.');
      return;
    }
    if (steps.length > 5) {
      setAssistantError('A task may have at most 5 steps.');
      return;
    }
    setAssistantBusy(true);
    try {
      const draft = await apiClient.draftTask({
        steps,
        language: defaultLanguage(languages),
        languages,
        task_type: taskType,
      });
      applyDraft(draft);
      reportDraftProblems(draft.problems);
    } catch (e) {
      setAssistantError(e instanceof Error ? e.message : String(e));
    } finally {
      setAssistantBusy(false);
    }
  };

  /** Refinement: apply a plain-English instruction to the current draft. */
  const refineDraft = async () => {
    setAssistantError(null);
    const instruction = quickInstruction.trim();
    if (!instruction) return;
    const draft: TaskCreateBody = {
      parts: draftsToParts(parts, languages),
      language: defaultLanguage(languages),
      languages,
      task_type: taskType,
      context_notes: contextNotes,
    };
    setAssistantBusy(true);
    try {
      const revised = await apiClient.draftTask({ draft, instruction });
      applyDraft(revised);
      reportDraftProblems(revised.problems);
      setQuickInstruction('');
    } catch (e) {
      setAssistantError(e instanceof Error ? e.message : String(e));
    } finally {
      setAssistantBusy(false);
    }
  };

  /** Validate + build the create/update body; returns null on invalid input. */
  const buildBody = (): TaskCreateBody | null => {
    setFormError(null);
    const problem = findStepDraftError(parts, languages);
    if (problem) {
      setFormError(problem.message);
      onError(problem.message);
      setActiveStep(problem.index);
      return null;
    }
    const defaultLang = defaultLanguage(languages);
    const cleaned: TaskPart[] = parts
      .filter((p) => p.prompt.trim().length > 0)
      .map((p) => {
        const scaffolds: Record<string, string> = {};
        for (const lang of languages) {
          const code = (p.scaffolds[lang] ?? '').trim();
          if (code) scaffolds[lang] = code;
        }
        const part: TaskPart = {
          key: p.key.trim(),
          prompt: p.prompt.trim(),
          max_score: clamp1to100(Number(p.max_score)) || 5,
          difficulty: clamp1to5(Number(p.difficulty)) || 2,
          tags: { primary: p.primary, secondary: p.secondary.slice(0, 2) },
        };
        if (scaffolds[defaultLang]) part.scaffold = scaffolds[defaultLang];
        if (languages.length > 1) part.scaffolds = scaffolds;
        if (p.pass_score.trim() !== '') {
          part.pass_score = Math.max(0, Math.min(part.max_score, Number(p.pass_score) || 0));
        }
        return part;
      });
    if (cleaned.length === 0) {
      const msg = 'Every step needs both a key and a prompt.';
      setFormError(msg);
      onError(msg);
      return null;
    }
    const body: TaskCreateBody = {
      parts: cleaned,
      task_type: taskType,
      language: defaultLanguage(languages),
      languages,
      is_public: isPublic,
    };
    if (contextNotes.trim()) body.context_notes = contextNotes.trim();
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
  const hasDraftContent = parts.some((p) => p.prompt.trim().length > 0);
  const activeMax = clamp1to100(Number(active.max_score)) || 5;
  const passScoreValue =
    active.pass_score.trim() !== ''
      ? Math.max(0, Math.min(activeMax, Number(active.pass_score) || 0))
      : autoPassScore(activeMax);
  const activeScaffoldIssues = scaffoldHygieneIssues(active.scaffolds[scaffoldLang]);

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

          {/* Curator-only AI assistant: draft from prompts, then refine. */}
          <section className="space-y-2 rounded-xl border border-dashed border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-2.5">
            <button
              type="button"
              onClick={() => setAssistantOpen((v) => !v)}
              className="flex w-full items-center gap-1.5 text-left text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]"
            >
              <span>{assistantOpen ? '▾' : '▸'}</span>
              AI assistant — fill or change the details
            </button>
            {assistantOpen && (
              <div className="space-y-2">
                {!task && (
                  <>
                    <textarea
                      value={quickText}
                      onChange={(e) => setQuickText(e.target.value)}
                      rows={6}
                      placeholder={
                        'One step prompt per block (separate with a blank line or ---).\n\n' +
                        'e.g. Implement scaled_dot_product_attention(Q, K, V).\n\n' +
                        'Now add causal masking so position i cannot attend to j > i.'
                      }
                      className={fieldCls}
                    />
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={() => void generateDraft()}
                        disabled={assistantBusy}
                        className="rounded-lg bg-[var(--color-accent)] px-3 py-1 text-[11px] font-semibold text-white disabled:opacity-40"
                      >
                        {assistantBusy ? 'Working…' : 'Fill in details'}
                      </button>
                      <span className="text-[10px] text-[var(--color-text-muted)]">
                        {splitStepPrompts(quickText).length} step(s) detected (max 5)
                      </span>
                    </div>
                  </>
                )}
                {hasDraftContent && (
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      value={quickInstruction}
                      onChange={(e) => setQuickInstruction(e.target.value)}
                      placeholder="Ask for a change, e.g. “make step 2 harder”"
                      className={`${fieldCls} flex-1`}
                    />
                    <button
                      type="button"
                      onClick={() => void refineDraft()}
                      disabled={assistantBusy || !quickInstruction.trim()}
                      className="rounded-lg border border-[var(--color-accent)]/50 px-3 py-1 text-[11px] font-semibold text-[var(--color-accent)] disabled:opacity-40"
                    >
                      {assistantBusy ? 'Working…' : 'Refine'}
                    </button>
                  </div>
                )}
                {assistantError && (
                  <p className="rounded-lg border border-[var(--color-error)]/30 bg-[var(--color-bg-primary)] px-3 py-1.5 text-[11px] text-[var(--color-error)]">
                    {assistantError}
                  </p>
                )}
              </div>
            )}
          </section>

          {/* Curator-only settings. */}
          <section className="space-y-2 rounded-xl border border-dashed border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-2.5">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
              Question settings — hidden from learners
            </p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <div className="col-span-2 sm:col-span-2">
                <span className={labelCls}>languages (first is the default)</span>
                <div className="flex flex-wrap gap-1">
                  {LANGUAGES.map((l) => {
                    const on = languages.includes(l);
                    return (
                      <button
                        key={l}
                        type="button"
                        onClick={() => toggleLanguage(l)}
                        aria-pressed={on}
                        className={`rounded-md border px-2 py-0.5 text-[11px] transition-colors ${
                          on
                            ? 'border-[var(--color-accent)]/50 bg-[var(--color-accent)]/10 text-[var(--color-accent)]'
                            : 'border-[var(--color-border-default)] text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]'
                        }`}
                      >
                        {l === 'cpp' ? 'C++' : l}
                      </button>
                    );
                  })}
                </div>
                <span className="mt-0.5 block text-[10px] text-[var(--color-text-muted)]">
                  Every selected language needs its own starter code below.
                </span>
              </div>
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
              <label className="flex items-center gap-2 self-end pb-1">
                <input
                  type="checkbox"
                  checked={isPublic}
                  onChange={(e) => setIsPublic(e.target.checked)}
                  className="h-3.5 w-3.5"
                />
                <span className="text-[11px] text-[var(--color-text-secondary)]">
                  Public in the question bank
                </span>
              </label>
            </div>
            <label className="block">
              <span className={labelCls}>context notes (background shown with the question)</span>
              <textarea
                value={contextNotes}
                onChange={(e) => setContextNotes(e.target.value)}
                rows={2}
                placeholder="2-4 sentences of prerequisite/confusion context (the AI assistant fills this)."
                className={fieldCls}
              />
            </label>
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
              onAddSkill={addSkill}
              primaryLabel="step primary *"
            />
          </section>

          {/* Starter code for the active step, one tab per declared language. */}
          <div>
            <div className="flex items-center gap-2">
              <p className={labelCls}>Starter code for this step (required for every language)</p>
              {languages.length > 1 && (
                <div className="ml-auto flex flex-wrap gap-1">
                  {languages.map((l) => (
                    <button
                      key={l}
                      type="button"
                      onClick={() => setScaffoldLang(l)}
                      className={`rounded-md border px-2 py-0.5 text-[11px] transition-colors ${
                        l === scaffoldLang
                          ? 'border-[var(--color-accent)]/50 bg-[var(--color-accent)]/10 text-[var(--color-accent)]'
                          : 'border-[var(--color-border-default)] text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]'
                      }`}
                    >
                      {l === 'cpp' ? 'C++' : l}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <CodeEditor
              key={`${task?.id ?? 'new'}:${activeStep}:${scaffoldLang}`}
              code={active.scaffolds[scaffoldLang] ?? ''}
              language={scaffoldLang}
              onChange={(v) =>
                updatePart(activeStep, {
                  scaffolds: { ...active.scaffolds, [scaffoldLang]: v },
                })
              }
              height="h-56"
              historyControls
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
