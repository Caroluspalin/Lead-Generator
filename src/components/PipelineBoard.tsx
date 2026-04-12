import React, { useState } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { PIPELINE_STATUSES } from '../types/agency';
import type { PipelineStatus, SavedAgency } from '../types/agency';
import { usePipeline } from '../context/PipelineContext';
import PipelineCard from './PipelineCard';

const PipelineBoard: React.FC = () => {
  const { savedAgencies, loading, error, updateStatus, updateNotes, removeFromPipeline, refresh } =
    usePipeline();
  const [activeTab, setActiveTab] = useState<PipelineStatus>('Shortlisted');

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
            {/* Tab Description */}
            <div className="mb-6 pb-4 border-b border-slate-100">
              <p className="text-sm text-slate-600">
                {statusDescriptions[activeTab]}
              </p>
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
    </section>
  );
};

export default PipelineBoard;
