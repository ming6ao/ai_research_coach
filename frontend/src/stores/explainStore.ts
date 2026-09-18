import { create } from 'zustand';
import { apiClient, storage, type Explanation, type ExplainBody } from '../api/client';

/** A panel card; server rows and optimistic pending cards share this shape. */
export interface ExplainItem {
  id: string;
  selectedText: string;
  context: string;
  sourceKind: string;
  taskId?: string;
  stepKey?: string;
  question?: string;
  parentId?: string;
  title?: string;
  answer?: string;
  relatedTerms: string[];
  status: 'pending' | 'ok' | 'error';
  error?: string;
  cached?: boolean;
  createdAt?: string;
}

export interface ExplainRequest {
  taskId: string;
  stepKey?: string;
  selectedText: string;
  context?: string;
  sourceKind: ExplainBody['source_kind'];
}

interface ExplainState {
  open: boolean;
  items: ExplainItem[];
  loadedSessionId: string | null;
  ask: (sessionId: string, req: ExplainRequest) => Promise<void>;
  askFollowUp: (sessionId: string, parent: ExplainItem, question: string) => Promise<void>;
  retry: (sessionId: string, id: string) => Promise<void>;
  loadForSession: (sessionId: string) => Promise<void>;
  openPanel: () => void;
  closePanel: () => void;
  togglePanel: () => void;
  clearSession: () => void;
}

const OPEN_KEY = 'ai_coach_explain_open';

function toItem(exp: Explanation): ExplainItem {
  return {
    id: exp.id,
    selectedText: exp.selected_text,
    context: exp.context ?? '',
    sourceKind: exp.source_kind ?? 'other',
    taskId: exp.task_id ?? undefined,
    stepKey: exp.step_key ?? undefined,
    question: exp.question ?? undefined,
    parentId: exp.parent_id ?? undefined,
    title: exp.title,
    answer: exp.explanation,
    relatedTerms: exp.related_terms ?? [],
    status: exp.status === 'error' ? 'error' : 'ok',
    cached: exp.cached,
    createdAt: exp.created_at,
  };
}

function pendingId(): string {
  try {
    return `pending-${crypto.randomUUID()}`;
  } catch {
    return `pending-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
}

export const useExplainStore = create<ExplainState>((set, get) => ({
  open: storage.get(OPEN_KEY) === '1',
  items: [],
  loadedSessionId: null,

  ask: async (sessionId, req) => {
    const id = pendingId();
    const item: ExplainItem = {
      id,
      selectedText: req.selectedText,
      context: req.context ?? '',
      sourceKind: req.sourceKind,
      taskId: req.taskId,
      stepKey: req.stepKey,
      relatedTerms: [],
      status: 'pending',
    };
    set((s) => ({ items: [...s.items, item], open: true }));
    storage.set(OPEN_KEY, '1');

    const body: ExplainBody = {
      task_id: req.taskId,
      selected_text: req.selectedText,
      context: req.context || undefined,
      source_kind: req.sourceKind,
      step_key: req.stepKey || undefined,
    };
    try {
      const res = await apiClient.explain(sessionId, body);
      set((s) => ({
        items: s.items.map((it) => (it.id === id ? toItem(res) : it)),
      }));
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      set((s) => ({
        items: s.items.map((it) =>
          it.id === id ? { ...it, status: 'error', error: msg } : it,
        ),
      }));
    }
  },

  askFollowUp: async (sessionId, parent, question) => {
    if (!parent.taskId || !question.trim()) return;
    const id = pendingId();
    const item: ExplainItem = {
      id,
      selectedText: question.trim(),
      context: '',
      sourceKind: parent.sourceKind,
      taskId: parent.taskId,
      stepKey: parent.stepKey,
      question: question.trim(),
      parentId: parent.id,
      relatedTerms: [],
      status: 'pending',
    };
    set((s) => ({ items: [...s.items, item], open: true }));
    storage.set(OPEN_KEY, '1');
    try {
      const res = await apiClient.explain(sessionId, {
        task_id: parent.taskId,
        step_key: parent.stepKey,
        selected_text: parent.selectedText,
        source_kind: parent.sourceKind as ExplainBody['source_kind'],
        question: question.trim(),
        parent_id: parent.id,
      });
      set((s) => ({ items: s.items.map((it) => (it.id === id ? toItem(res) : it)) }));
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      set((s) => ({
        items: s.items.map((it) =>
          it.id === id ? { ...it, status: 'error', error: msg } : it,
        ),
      }));
    }
  },

  retry: async (sessionId, id) => {
    const item = get().items.find((it) => it.id === id);
    if (!item || !item.taskId) return;
    set((s) => ({
      items: s.items.map((it) =>
        it.id === id ? { ...it, status: 'pending', error: undefined } : it,
      ),
    }));
    const body: ExplainBody = {
      task_id: item.taskId,
      step_key: item.stepKey,
      selected_text: item.selectedText,
      source_kind: item.sourceKind as ExplainBody['source_kind'],
      question: item.question,
      parent_id: item.parentId,
    };
    try {
      const res = await apiClient.explain(sessionId, body);
      set((s) => ({ items: s.items.map((it) => (it.id === id ? toItem(res) : it)) }));
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      set((s) => ({
        items: s.items.map((it) =>
          it.id === id ? { ...it, status: 'error', error: msg } : it,
        ),
      }));
    }
  },

  loadForSession: async (sessionId) => {
    if (get().loadedSessionId === sessionId) return;
    // A different session must not briefly show the previous session's cards.
    set({ loadedSessionId: sessionId, items: [] });
    try {
      const items = await apiClient.listExplanations(sessionId);
      set({ items: items.map(toItem) });
    } catch {
      // Non-fatal: the panel still works, history just won't be restored.
    }
  },

  openPanel: () => {
    storage.set(OPEN_KEY, '1');
    set({ open: true });
  },
  closePanel: () => {
    storage.set(OPEN_KEY, '0');
    set({ open: false });
  },
  togglePanel: () => {
    const next = !get().open;
    storage.set(OPEN_KEY, next ? '1' : '0');
    set({ open: next });
  },

  clearSession: () => set({ items: [], loadedSessionId: null }),
}));
