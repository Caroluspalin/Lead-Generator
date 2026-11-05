import React from 'react';
import { motion } from 'framer-motion';
import {
  Users,
  AlertTriangle,
  Smartphone,
  CheckCircle2,
  TrendingUp,
  ShieldAlert,
  HelpCircle,
} from 'lucide-react';
import { PIPELINE_STATUSES } from '../types/agency';
import type { PipelineStatus } from '../types/agency';
import { usePipeline } from '../context/PipelineContext';

const STAGE_COLORS: Record<PipelineStatus, string> = {
  Shortlisted: 'bg-slate-500',
  Contacted: 'bg-blue-500',
  'Proposal Received': 'bg-amber-500',
  Hired: 'bg-emerald-500',
  Rejected: 'bg-rose-400',
};

const STAGE_BG: Record<PipelineStatus, string> = {
  Shortlisted: 'bg-slate-50 border-slate-200 text-slate-700',
  Contacted: 'bg-blue-50 border-blue-200 text-blue-700',
  'Proposal Received': 'bg-amber-50 border-amber-200 text-amber-700',
  Hired: 'bg-emerald-50 border-emerald-200 text-emerald-700',
  Rejected: 'bg-rose-50 border-rose-200 text-rose-700',
};

const WEBSITE_STATUS_CONFIG = [
  { key: 'NO WEBSITE', label: 'No Website', color: 'bg-rose-500', icon: AlertTriangle },
  { key: 'BROKEN WEBSITE', label: 'Broken', color: 'bg-orange-500', icon: AlertTriangle },
  { key: 'INSECURE', label: 'Insecure', color: 'bg-amber-500', icon: ShieldAlert },
  { key: 'NOT MOBILE', label: 'Not Mobile', color: 'bg-yellow-500', icon: Smartphone },
  { key: 'WEBSITE OK', label: 'Website OK', color: 'bg-emerald-500', icon: CheckCircle2 },
  { key: 'UNKNOWN', label: 'Unknown', color: 'bg-slate-400', icon: HelpCircle },
] as const;

const DashboardView: React.FC = () => {
  const { savedAgencies, loading } = usePipeline();

  if (loading) {
    return (
      <section className="space-y-6">
        <div className="h-8 w-48 bg-slate-200 rounded animate-pulse" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-32 bg-slate-200 rounded-xl animate-pulse" />
          ))}
        </div>
      </section>
    );
  }

  const total = savedAgencies.length;

  const stageCounts = PIPELINE_STATUSES.reduce(
    (acc, s) => {
      acc[s] = savedAgencies.filter((a) => a.pipeline_status === s).length;
      return acc;
    },
    {} as Record<PipelineStatus, number>,
  );

  const websiteCounts = WEBSITE_STATUS_CONFIG.map((ws) => ({
    ...ws,
    count: savedAgencies.filter((a) => a.website_status === ws.key).length,
  }));

  const opportunityCount = savedAgencies.filter(
    // UNKNOWN ei ole varmistettu myyntipaikka
    (a) => a.website_status && a.website_status !== 'WEBSITE OK' && a.website_status !== 'UNKNOWN',
  ).length;

  const conversionRate =
    total > 0
      ? Math.round(((stageCounts['Contacted'] + stageCounts['Proposal Received'] + stageCounts['Hired']) / total) * 100)
      : 0;

  return (
    <section className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-900 mb-2">Dashboard</h2>
        <p className="text-sm text-slate-600">
          Overview of your pipeline performance and lead quality
        </p>
      </div>

      {total === 0 ? (
        <div className="p-12 text-center bg-white border-2 border-dashed border-slate-300 rounded-2xl">
          <p className="text-slate-500 font-medium mb-2">No data yet</p>
          <p className="text-sm text-slate-400">
            Save leads to your pipeline to see analytics here
          </p>
        </div>
      ) : (
        <>
          {/* KPI Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <KpiCard label="Total Leads" value={total} icon={Users} color="bg-indigo-50 text-indigo-600" />
            <KpiCard label="Opportunities" value={opportunityCount} icon={TrendingUp} color="bg-amber-50 text-amber-600" />
            <KpiCard label="Contacted+" value={`${conversionRate}%`} icon={CheckCircle2} color="bg-emerald-50 text-emerald-600" />
            <KpiCard label="Hired" value={stageCounts['Hired']} icon={Users} color="bg-purple-50 text-purple-600" />
          </div>

          {/* Pipeline Funnel */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6">
            <h3 className="text-sm font-bold text-slate-800 uppercase tracking-wide mb-5">
              Pipeline Funnel
            </h3>
            <div className="space-y-3">
              {PIPELINE_STATUSES.map((status) => {
                const count = stageCounts[status];
                const pct = total > 0 ? (count / total) * 100 : 0;
                return (
                  <div key={status} className="flex items-center gap-4">
                    <span
                      className={`w-36 text-xs font-semibold px-3 py-1.5 rounded-lg border ${STAGE_BG[status]}`}
                    >
                      {status}
                    </span>
                    <div className="flex-1 h-7 bg-slate-100 rounded-full overflow-hidden">
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${pct}%` }}
                        transition={{ duration: 0.6, ease: 'easeOut' }}
                        className={`h-full rounded-full ${STAGE_COLORS[status]}`}
                      />
                    </div>
                    <span className="w-16 text-right text-sm font-bold text-slate-700">
                      {count}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Website Status Breakdown */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6">
            <h3 className="text-sm font-bold text-slate-800 uppercase tracking-wide mb-5">
              Website Status
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {websiteCounts.map((ws) => {
                const Icon = ws.icon;
                const pct = total > 0 ? Math.round((ws.count / total) * 100) : 0;
                return (
                  <div
                    key={ws.key}
                    className="bg-slate-50 border border-slate-200 rounded-xl p-4 text-center"
                  >
                    <Icon size={20} className="mx-auto text-slate-400 mb-2" />
                    <p className="text-2xl font-bold text-slate-900">{ws.count}</p>
                    <p className="text-xs font-medium text-slate-500 mt-1">{ws.label}</p>
                    <div className="mt-3 h-2 bg-slate-200 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${ws.color}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <p className="text-xs text-slate-400 mt-1">{pct}%</p>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Recent Activity */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6">
            <h3 className="text-sm font-bold text-slate-800 uppercase tracking-wide mb-5">
              Recently Added
            </h3>
            <div className="divide-y divide-slate-100">
              {savedAgencies.slice(0, 8).map((a) => (
                <div key={a.id} className="flex items-center justify-between py-3">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-slate-800 truncate">{a.name}</p>
                    <p className="text-xs text-slate-500">{a.city}</p>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    {a.website_status && (
                      <span
                        className={`px-2 py-1 rounded text-[10px] font-semibold border ${
                          a.website_status === 'WEBSITE OK'
                            ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                            : a.website_status === 'NO WEBSITE'
                              ? 'bg-rose-50 text-rose-700 border-rose-200'
                              : 'bg-amber-50 text-amber-700 border-amber-200'
                        }`}
                      >
                        {a.website_status}
                      </span>
                    )}
                    <span
                      className={`px-2 py-1 rounded text-[10px] font-semibold border ${STAGE_BG[a.pipeline_status]}`}
                    >
                      {a.pipeline_status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </section>
  );
};

interface KpiCardProps {
  label: string;
  value: number | string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  color: string;
}

const KpiCard: React.FC<KpiCardProps> = ({ label, value, icon: Icon, color }) => (
  <motion.div
    initial={{ opacity: 0, y: 10 }}
    animate={{ opacity: 1, y: 0 }}
    className="bg-white rounded-xl border border-slate-200 shadow-sm p-5"
  >
    <div className={`inline-flex p-2.5 rounded-lg mb-3 ${color}`}>
      <Icon size={18} />
    </div>
    <p className="text-2xl font-bold text-slate-900">{value}</p>
    <p className="text-xs font-medium text-slate-500 mt-1">{label}</p>
  </motion.div>
);

export default DashboardView;
