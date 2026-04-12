import React, { useState, useCallback } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  AlertTriangle,
  RefreshCw,
  ArrowRightLeft,
  Sparkles,
  Trash2,
  X,
  CheckSquare,
  Loader2,
  Download,
} from 'lucide-react';
import { toast } from 'sonner';
import { PIPELINE_STATUSES } from '../types/agency';
import type { PipelineStatus } from '../types/agency';
import { usePipeline } from '../context/PipelineContext';
import PipelineCard from './PipelineCard';

const API_BASE = 'http://127.0.0.1:8000';

const BATCH_SIZE = 5;

async function processInBatches<T>(
  items: T[],
  fn: (item: T) => Promise<void>,
): Promise<{ ok: number; failed: number }> {
  let ok = 0;
  let failed = 0;
  for (let i = 0; i < items.length; i += BATCH_SIZE) {
    const batch = items.slice(i, i + BATCH_SIZE);
    const results = await Promise.allSettled(batch.map(fn));
    for (const r of results) {
      if (r.status === 'fulfilled') ok++;
      else failed++;
    }
  }
  return { ok, failed };
}

const PipelineBoard: React.FC = () => {
  const { savedAgencies, loading, error, updateStatus, updateNotes, removeFromPipeline, refresh } =
    usePipeline();
  const [activeTab, setActiveTab] = useState<PipelineStatus>('Shortlisted');
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [bulkLoading, setBulkLoading] = useState(false);
  const [stageMenuOpen, setStageMenuOpen] = useState(false);

  const toggleSelect = useCallback((id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectAllInTab = useCallback(() => {
    const tabIds = savedAgencies
      .filter((a) => a.pipeline_status === activeTab)
      .map((a) => a.id);
    setSelectedIds((prev) => {
      const allSelected = tabIds.every((id) => prev.has(id));
      const next = new Set(prev);
      if (allSelected) {
        tabIds.forEach((id) => next.delete(id));
      } else {
        tabIds.forEach((id) => next.add(id));
      }
      return next;
    });
  }, [savedAgencies, activeTab]);

  const clearSelection = () => setSelectedIds(new Set());

  const handleBulkStatusChange = async (status: PipelineStatus) => {
    setBulkLoading(true);
    setStageMenuOpen(false);
    const ids = [...selectedIds];
    const { ok, failed } = await processInBatches(ids, (id) => updateStatus(id, status));
    if (ok > 0) toast.success(`${ok} lead(s) moved to ${status}`);
    if (failed > 0) toast.error(`${failed} lead(s) failed to update`);
    clearSelection();
    setBulkLoading(false);
  };

  const handleBulkGenerateEmails = async () => {
    setBulkLoading(true);
    const ids = [...selectedIds];
    let ok = 0;
    let failed = 0;
    for (let i = 0; i < ids.length; i += BATCH_SIZE) {
      const batch = ids.slice(i, i + BATCH_SIZE);
      const results = await Promise.allSettled(
        batch.map(async (id) => {
          const res = await fetch(`${API_BASE}/leads/${id}/generate-email`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
          });
          if (!res.ok) throw new Error(`${res.status}`);
        }),
      );
      for (const r of results) {
        if (r.status === 'fulfilled') ok++;
        else failed++;
      }
    }
    if (ok > 0) toast.success(`${ok} email draft(s) generated`);
    if (failed > 0) toast.error(`${failed} draft(s) failed`);
    clearSelection();
    setBulkLoading(false);
  };

  const handleExportCsv = () => {
    const idsParam = [...selectedIds].join(',');
    const url = `${API_BASE}/leads/export?ids=${idsParam}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = 'leads_export.csv';
    a.click();
  };

  const handleBulkDelete = async () => {
    setBulkLoading(true);
    const ids = [...selectedIds];
    const { ok, failed } = await processInBatches(ids, (id) => removeFromPipeline(id));
    if (ok > 0) toast.success(`${ok} lead(s) removed`);
    if (failed > 0) toast.error(`${failed} lead(s) failed to remove`);
    clearSelection();
    setBulkLoading(false);
  };

  const handleStatusChange = async (id: number, status: PipelineStatus) => {
    try {
      await updateStatus(id, status);
      toast.success(`Status changed to ${status}`);
    } catch {
      toast.error('Failed to update status');
    }
  };

  const handleNotesChange = async (id: number, notes: string) => {
    try {
      await updateNotes(id, notes);
      toast.success('Notes saved');
    } catch {
      toast.error('Failed to save notes');
    }
  };

  const handleRemove = async (id: number) => {
    try {
      await removeFromPipeline(id);
      toast.success('Lead removed');
    } catch {
      toast.error('Failed to remove lead');
    }
  };

  const statusDescriptions: Record<PipelineStatus, string> = {
    Shortlisted: 'Potential businesses worth a closer look',
    Contacted: 'You have reached out or scheduled an intro',
    'Proposal Received': 'They have sent a proposal or pricing',
    Hired: 'You decided to work with this business',
    Rejected: 'Not a fit for now',
  };

  const getTabCount = (status: PipelineStatus) => {
    return savedAgencies.filter((agency) => agency.pipeline_status === status)
      .length;
  };

  const activeAgencies = savedAgencies.filter(
    (agency) => agency.pipeline_status === activeTab,
  );

  return (
    <section>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-slate-900 mb-2">
          My Pipeline
        </h2>
        <p className="text-sm text-slate-600">
          Track your prospects from first contact to final decision
        </p>
      </div>

      {loading ? (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <div className="border-b border-slate-200 bg-slate-50">
            <div className="flex gap-1 p-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-10 flex-1 bg-slate-200 rounded-md animate-pulse" />
              ))}
            </div>
          </div>
          <div className="p-6 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="animate-pulse border border-slate-200 rounded-xl p-5 space-y-3">
                <div className="h-5 w-3/4 bg-slate-200 rounded" />
                <div className="h-4 w-1/2 bg-slate-100 rounded" />
                <div className="h-4 w-2/3 bg-slate-100 rounded" />
                <div className="h-8 w-full bg-slate-100 rounded-lg mt-2" />
              </div>
            ))}
          </div>
        </div>
      ) : error ? (
        <div className="p-8 text-center bg-white border border-red-100 rounded-2xl">
          <AlertTriangle size={32} className="mx-auto text-red-400 mb-3" />
          <p className="text-red-700 font-medium mb-1">Failed to load</p>
          <p className="text-sm text-red-500 mb-4">{error}</p>
          <button
            onClick={refresh}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-red-700 bg-red-50 hover:bg-red-100 rounded-lg transition-colors"
          >
            <RefreshCw size={14} />
            Retry
          </button>
        </div>
      ) : savedAgencies.length === 0 ? (
        <div className="p-12 text-center bg-white border-2 border-dashed border-slate-300 rounded-2xl">
          <p className="text-slate-500 mb-2 font-medium">
            Your pipeline is empty
          </p>
          <p className="text-sm text-slate-400">
            Use <span className="font-semibold text-indigo-600">Search Businesses</span> or{' '}
            <span className="font-semibold text-indigo-600">Add Manually</span> to get started
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          {/* Tabs */}
          <div className="border-b border-slate-200 bg-slate-50">
            <div className="flex overflow-x-auto">
              {PIPELINE_STATUSES.map((status) => {
                const count = getTabCount(status);
                const isActive = activeTab === status;
                return (
                  <button
                    key={status}
                    onClick={() => setActiveTab(status)}
                    className={`relative px-6 py-4 text-sm font-medium transition-all whitespace-nowrap ${
                      isActive
                        ? 'text-indigo-700 bg-white border-b-2 border-indigo-600'
                        : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      {status}
                      {count > 0 && (
                        <span
                          className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
                            isActive
                              ? 'bg-indigo-100 text-indigo-700'
                              : 'bg-slate-200 text-slate-600'
                          }`}
                        >
                          {count}
                        </span>
                      )}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Content */}
          <div className="p-6">
            {/* Tab Description + Select All */}
            <div className="mb-6 pb-4 border-b border-slate-100 flex items-center justify-between">
              <p className="text-sm text-slate-600">
                {statusDescriptions[activeTab]}
              </p>
              {activeAgencies.length > 0 && (
                <button
                  onClick={selectAllInTab}
                  className="flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-indigo-600 transition-colors"
                >
                  <CheckSquare size={14} />
                  {activeAgencies.every((a) => selectedIds.has(a.id))
                    ? 'Deselect All'
                    : 'Select All'}
                </button>
              )}
            </div>

            {/* Cards Grid */}
            {activeAgencies.length === 0 ? (
              <div className="py-12 text-center">
                <p className="text-slate-400 text-sm">
                  No businesses in <span className="font-medium text-slate-600">{activeTab}</span> yet
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {activeAgencies.map((agency) => (
                  <PipelineCard
                    key={agency.id}
                    agency={agency}
                    selected={selectedIds.has(agency.id)}
                    onToggleSelect={toggleSelect}
                    onStatusChange={handleStatusChange}
                    onNotesChange={handleNotesChange}
                    onRemove={handleRemove}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Bulk Actions Toolbar */}
      <AnimatePresence>
        {selectedIds.size > 0 && (
          <motion.div
            initial={{ y: 80, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 80, opacity: 0 }}
            transition={{ type: 'spring', damping: 25, stiffness: 300 }}
            className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50"
          >
            <div className="flex items-center gap-3 px-5 py-3 bg-slate-900 text-white rounded-2xl shadow-2xl border border-slate-700">
              <span className="text-sm font-semibold whitespace-nowrap">
                {selectedIds.size} selected
              </span>

              <div className="w-px h-6 bg-slate-700" />

              {/* Move Stage */}
              <div className="relative">
                <button
                  onClick={() => setStageMenuOpen(!stageMenuOpen)}
                  disabled={bulkLoading}
                  className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium bg-slate-800 hover:bg-slate-700 rounded-lg transition-colors disabled:opacity-50"
                >
                  <ArrowRightLeft size={14} />
                  Move
                </button>
                {stageMenuOpen && (
                  <div className="absolute bottom-full mb-2 left-0 bg-white border border-slate-200 rounded-xl shadow-xl py-1 min-w-[180px]">
                    {PIPELINE_STATUSES.map((status) => (
                      <button
                        key={status}
                        onClick={() => handleBulkStatusChange(status)}
                        className="w-full text-left px-4 py-2.5 text-sm text-slate-700 hover:bg-indigo-50 hover:text-indigo-700 transition-colors"
                      >
                        {status}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Generate AI Drafts */}
              <button
                onClick={handleBulkGenerateEmails}
                disabled={bulkLoading}
                className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium bg-purple-600 hover:bg-purple-500 rounded-lg transition-colors disabled:opacity-50"
              >
                {bulkLoading ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                AI Drafts
              </button>

              {/* Export CSV */}
              <button
                onClick={handleExportCsv}
                disabled={bulkLoading}
                className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium bg-emerald-600 hover:bg-emerald-500 rounded-lg transition-colors disabled:opacity-50"
              >
                <Download size={14} />
                CSV
              </button>

              {/* Delete */}
              <button
                onClick={handleBulkDelete}
                disabled={bulkLoading}
                className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium bg-rose-600 hover:bg-rose-500 rounded-lg transition-colors disabled:opacity-50"
              >
                <Trash2 size={14} />
                Delete
              </button>

              <div className="w-px h-6 bg-slate-700" />

              {/* Clear */}
              <button
                onClick={clearSelection}
                className="p-2 text-slate-400 hover:text-white transition-colors"
                aria-label="Clear selection"
              >
                <X size={16} />
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
};

export default PipelineBoard;
