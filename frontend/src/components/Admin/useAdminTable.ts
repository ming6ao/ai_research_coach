import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  apiClient,
  type AdminTableMeta,
  type AdminTableQuery,
} from '../../api/client';
import { FILTERS_PER_TABLE, totalPages } from './adminHelpers';

export type AdminGate = 'checking' | 'ok' | 'denied' | 'error';

export function useAdminTable() {
  const [gate, setGate] = useState<AdminGate>('checking');
  const [tables, setTables] = useState<AdminTableMeta[]>([]);
  const [activeTable, setActiveTable] = useState<string>('tasks');
  const [query, setQuery] = useState<AdminTableQuery>({ page: 1, page_size: 25, order: 'desc' });
  const [searchInput, setSearchInput] = useState('');
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const meta = useMemo(
    () => tables.find((t) => t.name === activeTable) ?? null,
    [tables, activeTable],
  );
  const editableCols = useMemo(
    () => (meta ? meta.columns.filter((c) => c.editable) : []),
    [meta],
  );
  const filterKeys = FILTERS_PER_TABLE[activeTable] ?? [];
  const pages = totalPages(total, query.page_size ?? 25);

  // Gate + table metadata on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const who = await apiClient.adminWhoami();
        if (cancelled) return;
        if (!who.is_admin) {
          setGate('denied');
          return;
        }
        const res = await apiClient.adminTables();
        if (cancelled) return;
        setTables(res.tables);
        if (res.tables.length > 0 && !res.tables.some((t) => t.name === 'tasks')) {
          setActiveTable(res.tables[0].name);
        }
        setGate('ok');
      } catch {
        if (!cancelled) setGate('error');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const loadRows = useCallback(async (table: string, q: AdminTableQuery) => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.adminTableRows(table, q);
      setRows(res.rows);
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setRows([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, []);

  // Reload whenever the table or applied query changes.
  useEffect(() => {
    if (gate !== 'ok') return;
    void loadRows(activeTable, query);
  }, [gate, activeTable, query, loadRows]);

  // Debounce the free-text search into the applied query.
  useEffect(() => {
    const t = setTimeout(() => {
      setQuery((prev) => {
        const next = searchInput.trim();
        if ((prev.q ?? '') === next) return prev;
        return { ...prev, q: next || undefined, page: 1 };
      });
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const switchTable = (name: string) => {
    setActiveTable(name);
    setQuery({ page: 1, page_size: query.page_size ?? 25, order: 'desc' });
    setSearchInput('');
    setNotice(null);
  };

  const setSort = (col: string) => {
    setQuery((prev) => ({
      ...prev,
      sort: col,
      order: prev.sort === col && prev.order === 'desc' ? 'asc' : 'desc',
      page: 1,
    }));
  };

  const refreshTables = useCallback(async () => {
    try {
      const res = await apiClient.adminTables();
      setTables(res.tables);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [setError]);

  return {
    gate,
    tables,
    activeTable,
    meta,
    editableCols,
    filterKeys,
    pages,
    query,
    setQuery,
    searchInput,
    setSearchInput,
    rows,
    total,
    loading,
    error,
    setError,
    notice,
    setNotice,
    loadRows,
    switchTable,
    setSort,
    refreshTables,
  };
}

export type AdminTable = ReturnType<typeof useAdminTable>;
