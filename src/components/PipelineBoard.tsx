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
import { apiFetch } from '../lib/api';
import PipelineCard from './PipelineCard';

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
          const res = await apiFetch(`/leads/${id}/generate-email`, {
            method: 'POST',
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

  const handleExportCsv = async () => {
    const idsParam = [...selectedIds].join(',');
    try {
      const res = await apiFetch(`/leads/export?ids=${idsParam}`);
      if (!res.ok) throw new Error(`${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'leads_export.csv';
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error('CSV export failed');
    }
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

  const toolbarButton =
    'flex items-center gap-1.5 h-control-sm px-2.5 text-xs font-medium text-fg border border-line-strong rounded hover:bg-subtle transition-colors disabled:opacity-50';

  return (
    <section>
      <header className="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="text-xl font-semibold tracking-tight text-fg">Pipeline</h1>
        <p className="text-sm text-fg-subtle">Track prospects from first contact to decision</p>
      </header>

      {loading ? (
        <div>
          <div className="flex gap-5 border-b border-line pb-2.5 mb-4">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-4 w-20 bg-raised rounded-sm animate-pulse" />
            ))}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="animate-pulse bg-surface border border-line rounded p-card space-y-3">
                <div className="h-4 w-3/4 bg-raised rounded-sm" />
                <div className="h-3 w-1/2 bg-subtle rounded-sm" />
                <div className="h-3 w-2/3 bg-subtle rounded-sm" />
                <div className="h-control-sm w-full bg-subtle rounded mt-2" />
              </div>
            ))}
          </div>
        </div>
      ) : error ? (
        <div role="alert" className="p-8 text-center bg-surface border border-danger/30 rounded">
          <AlertTriangle size={24} className="mx-auto text-danger mb-3" />
          <p className="text-fg font-medium mb-1">Failed to load</p>
          <p className="text-sm text-fg-muted mb-4">{error}</p>
          <button
            onClick={refresh}
            className="inline-flex items-center gap-2 h-control px-3 text-sm font-medium text-fg border border-line-strong hover:bg-raised rounded transition-colors"
          >
            <RefreshCw size={14} />
            Retry
          </button>
        </div>
      ) : savedAgencies.length === 0 ? (
        <div className="p-12 text-center border border-dashed border-line-strong rounded">
          <p className="text-fg mb-1 font-medium">
            Your pipeline is empty
          </p>
          <p className="text-sm text-fg-subtle">
            Use <span className="font-medium text-fg-muted">Search</span> or{' '}
            <span className="font-medium text-fg-muted">Add manually</span> to get started
          </p>
        </div>
      ) : (
        <div>
          {/* Tabs */}
          <div className="border-b border-line">
            <div className="flex gap-6 overflow-x-auto" role="tablist" aria-label="Pipeline stages">
              {PIPELINE_STATUSES.map((status) => {
                const count = getTabCount(status);
                const isActive = activeTab === status;
                return (
                  <button
                    key={status}
                    role="tab"
                    aria-selected={isActive}
                    onClick={() => setActiveTab(status)}
                    className={`relative -mb-px flex items-center gap-2 pt-1 pb-2.5 text-sm font-medium whitespace-nowrap border-b transition-colors ${
                      isActive
                        ? 'text-fg border-fg'
                        : 'text-fg-muted border-transparent hover:text-fg'
                    }`}
                  >
                    {status}
                    <span className="min-w-[18px] px-1 rounded-sm bg-raised text-2xs tabular-nums text-fg-subtle">
                      {count}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Content */}
          <div className="pt-4">
            {/* Tab Description + Select All */}
            <div className="mb-3.5 flex items-center justify-between gap-3">
              <p className="text-sm text-fg-muted">
                {statusDescriptions[activeTab]}
              </p>
              {activeAgencies.length > 0 && (
                <button
                  onClick={selectAllInTab}
                  className="flex items-center gap-1.5 h-control-sm px-2.5 text-xs font-medium text-fg-muted border border-line-strong rounded hover:text-fg hover:bg-subtle transition-colors"
                >
                  <CheckSquare size={13} />
                  {activeAgencies.every((a) => selectedIds.has(a.id))
                    ? 'Deselect all'
                    : 'Select all'}
                </button>
              )}
            </div>

            {/* Cards Grid */}
            {activeAgencies.length === 0 ? (
              <div className="py-12 text-center border border-dashed border-line rounded">
                <p className="text-fg-subtle text-sm">
                  No businesses in <span className="font-medium text-fg-muted">{activeTab}</span> yet
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 items-start">
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
            <div className="flex items-center gap-2 pl-4 pr-2 py-2 bg-raised text-fg rounded-lg border border-line-strong shadow-popover">
              <span className="text-sm font-medium tabular-nums whitespace-nowrap">
                {selectedIds.size} selected
              </span>

              <div className="w-px h-5 bg-line-strong mx-1" />

              {/* Move Stage */}
              <div className="relative">
                <button
                  onClick={() => setStageMenuOpen(!stageMenuOpen)}
                  disabled={bulkLoading}
                  aria-expanded={stageMenuOpen}
                  className={toolbarButton}
                >
                  <ArrowRightLeft size={13} />
                  Move
                </button>
                {stageMenuOpen && (
                  <div className="absolute bottom-full mb-2 left-0 bg-raised border border-line-strong rounded-lg py-1 min-w-[180px] shadow-popover">
                    {PIPELINE_STATUSES.map((status) => (
                      <button
                        key={status}
                        onClick={() => handleBulkStatusChange(status)}
                        className="w-full text-left px-3 py-1.5 text-sm text-fg-muted hover:bg-subtle hover:text-fg transition-colors"
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
                className={toolbarButton}
              >
                {bulkLoading ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
                AI drafts
              </button>

              {/* Export CSV */}
              <button
                onClick={handleExportCsv}
                disabled={bulkLoading}
                className={toolbarButton}
              >
                <Download size={13} />
                CSV
              </button>

              {/* Delete */}
              <button
                onClick={handleBulkDelete}
                disabled={bulkLoading}
                className="flex items-center gap-1.5 h-control-sm px-2.5 text-xs font-medium text-danger border border-danger/30 rounded hover:bg-danger/10 transition-colors disabled:opacity-50"
              >
                <Trash2 size={13} />
                Delete
              </button>

              <div className="w-px h-5 bg-line-strong mx-1" />

              {/* Clear */}
              <button
                onClick={clearSelection}
                className="grid size-control-sm place-content-center rounded text-fg-subtle hover:text-fg hover:bg-subtle transition-colors"
                aria-label="Clear selection"
              >
                <X size={14} />
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
};

export default PipelineBoard;
