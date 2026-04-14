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
    <section className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-900 mb-2">Search History</h2>
          <p className="text-sm text-slate-600">
            Your past searches — click to re-run any search instantly
          </p>
        </div>
        <button
          onClick={fetchHistory}
          className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-slate-600 hover:text-indigo-600 bg-white border border-slate-200 rounded-lg hover:border-indigo-200 transition-colors"
        >
          <RefreshCw size={14} />
          Refresh
        </button>
      </div>

      {loading ? (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-12 flex items-center justify-center">
          <Loader2 size={24} className="animate-spin text-slate-400" />
        </div>
      ) : uniqueEntries.length === 0 ? (
        <div className="p-12 text-center bg-white border-2 border-dashed border-slate-300 rounded-2xl">
          <History size={32} className="mx-auto text-slate-300 mb-3" />
          <p className="text-slate-500 font-medium mb-2">No searches yet</p>
          <p className="text-sm text-slate-400">
            Your search history will appear here after running searches
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <div className="divide-y divide-slate-100">
            <AnimatePresence>
              {uniqueEntries.map((entry) => (
                <motion.div
                  key={`${entry.business_type}-${entry.city}`}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0, height: 0 }}
                  className="flex items-center gap-4 px-6 py-4 hover:bg-slate-50 transition-colors group"
                >
                  <div className="p-2.5 bg-indigo-50 rounded-lg shrink-0">
                    <Search size={16} className="text-indigo-600" />
                  </div>

                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-slate-800">
                      {entry.business_type}
                    </p>
                    <div className="flex items-center gap-3 mt-1">
                      <span className="flex items-center gap-1 text-xs text-slate-500">
                        <MapPin size={11} />
                        {entry.city}
                      </span>
                      <span className="flex items-center gap-1 text-xs text-slate-500">
                        <Clock size={11} />
                        {formatDate(entry.searched_at)}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 shrink-0">
                    <div className="text-right">
                      <p className="text-sm font-bold text-slate-700">
                        {entry.result_count}
                      </p>
                      <p className="text-[10px] text-slate-400">results</p>
                    </div>

                    {entry.searchCount > 1 && (
                      <span className="px-2 py-1 bg-indigo-50 text-indigo-600 text-[10px] font-bold rounded-full">
                        {entry.searchCount}x
                      </span>
                    )}

                    {onReSearch && (
                      <button
                        onClick={() => onReSearch(entry.business_type, entry.city)}
                        className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg transition-colors opacity-0 group-hover:opacity-100"
                      >
                        <Search size={12} />
                        Re-search
                      </button>
                    )}

                    <button
                      onClick={() => handleDelete(entry.id)}
                      className="p-2 text-slate-300 hover:text-rose-500 transition-colors opacity-0 group-hover:opacity-100"
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
