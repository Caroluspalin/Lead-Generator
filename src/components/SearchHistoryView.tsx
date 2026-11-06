import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  History,
  Search,
  MapPin,
  Trash2,
  RefreshCw,
  Loader2,
  Clock,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiFetch } from '../lib/api';

interface HistoryEntry {
  id: number;
  business_type: string;
  city: string;
  result_count: number;
  searched_at: string;
}

interface SearchHistoryViewProps {
  onReSearch?: (businessType: string, city: string) => void;
}

const SearchHistoryView: React.FC<SearchHistoryViewProps> = ({ onReSearch }) => {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`/search-history`);
      if (!res.ok) throw new Error(`${res.status}`);
      setEntries(await res.json());
    } catch {
      toast.error('Failed to load search history');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  const handleDelete = async (id: number) => {
    try {
      const res = await apiFetch(`/search-history/${id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`${res.status}`);
      setEntries((prev) => prev.filter((e) => e.id !== id));
      toast.success('Entry removed');
    } catch {
      toast.error('Failed to delete entry');
    }
  };

  const formatDate = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleDateString('fi-FI', {
      day: 'numeric',
      month: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  // Ryhmitellään uniikit hakuparit ja lasketaan hakukerrat
  const grouped = entries.reduce(
    (acc, e) => {
      const key = `${e.business_type}|||${e.city}`;
      if (!acc[key]) {
        acc[key] = { ...e, searchCount: 1 };
      } else {
        acc[key].searchCount++;
        if (e.searched_at > acc[key].searched_at) {
          acc[key].searched_at = e.searched_at;
          acc[key].result_count = e.result_count;
          acc[key].id = e.id;
        }
      }
      return acc;
    },
    {} as Record<string, HistoryEntry & { searchCount: number }>,
  );

  const uniqueEntries = Object.values(grouped).sort(
    (a, b) => new Date(b.searched_at).getTime() - new Date(a.searched_at).getTime(),
  );

  return (
    <section className="space-y-5">
      <div className="flex items-center justify-between gap-4">
        <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="text-xl font-semibold tracking-tight text-fg">Search history</h1>
          <p className="text-sm text-fg-subtle">
            Your past searches. Re-run any search with one click.
          </p>
        </header>
        <button
          onClick={fetchHistory}
          className="flex shrink-0 items-center gap-1.5 h-control-sm px-2.5 text-xs font-medium text-fg-muted border border-line-strong rounded hover:text-fg hover:bg-subtle transition-colors"
        >
          <RefreshCw size={13} />
          Refresh
        </button>
      </div>

      {loading ? (
        <div role="status" className="bg-surface rounded border border-line p-12 flex items-center justify-center">
          <Loader2 size={20} className="animate-spin text-fg-subtle" />
        </div>
      ) : uniqueEntries.length === 0 ? (
        <div className="p-12 text-center border border-dashed border-line-strong rounded">
          <History size={24} className="mx-auto text-fg-subtle mb-3" />
          <p className="text-fg font-medium mb-1">No searches yet</p>
          <p className="text-sm text-fg-subtle">
            Your search history will appear here after running searches
          </p>
        </div>
      ) : (
        <div className="bg-surface rounded border border-line overflow-hidden">
          <div className="grid grid-cols-[minmax(0,1fr)_140px_140px_72px_176px] items-center gap-4 px-card py-2 border-b border-line bg-canvas text-2xs font-medium text-fg-subtle">
            <span>Industry</span>
            <span>City</span>
            <span>Last searched</span>
            <span className="text-right">Results</span>
            <span className="sr-only">Actions</span>
          </div>
          <div className="divide-y divide-line">
            <AnimatePresence>
              {uniqueEntries.map((entry) => (
                <motion.div
                  key={`${entry.business_type}-${entry.city}`}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0, height: 0 }}
                  className="grid grid-cols-[minmax(0,1fr)_140px_140px_72px_176px] items-center gap-4 px-card py-2.5 hover:bg-subtle transition-colors group"
                >
                  <p className="flex min-w-0 items-center gap-2 text-sm font-medium text-fg">
                    <span className="truncate">{entry.business_type}</span>
                    {entry.searchCount > 1 && (
                      <span className="shrink-0 px-1 rounded-sm bg-raised text-2xs font-normal tabular-nums text-fg-subtle">
                        {entry.searchCount}×
                      </span>
                    )}
                  </p>
                  <span className="flex items-center gap-1.5 text-sm text-fg-muted truncate">
                    <MapPin size={12} className="shrink-0 text-fg-subtle" />
                    {entry.city}
                  </span>
                  <span className="flex items-center gap-1.5 text-xs tabular-nums text-fg-subtle whitespace-nowrap">
                    <Clock size={12} className="shrink-0" />
                    {formatDate(entry.searched_at)}
                  </span>
                  <span className="text-right text-sm font-medium tabular-nums text-fg">
                    {entry.result_count}
                  </span>

                  {/* Näkyy myös näppäimistöllä (focus-within), ei vain hiirellä */}
                  <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity">
                    {onReSearch && (
                      <button
                        onClick={() => onReSearch(entry.business_type, entry.city)}
                        className="flex items-center gap-1.5 h-control-sm px-2.5 text-xs font-medium text-accent-fg bg-accent hover:bg-accent-hover rounded transition-colors"
                      >
                        <Search size={12} />
                        Re-search
                      </button>
                    )}

                    <button
                      onClick={() => handleDelete(entry.id)}
                      className="grid size-control-sm place-content-center rounded text-fg-subtle hover:text-danger hover:bg-danger/10 transition-colors"
                      aria-label="Delete entry"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        </div>
      )}
    </section>
  );
};

export default SearchHistoryView;
