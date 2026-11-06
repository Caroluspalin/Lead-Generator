import React from 'react';
import { motion } from 'framer-motion';
import { Users, CheckCircle2, TrendingUp } from 'lucide-react';
import { PIPELINE_STATUSES } from '../types/agency';
import type { PipelineStatus } from '../types/agency';
import { usePipeline } from '../context/PipelineContext';
import { StatusBadge } from './ScoreBadge';

// Pipeline-vaiheet ovat neutraaleja; väri vain sivun tilalla, jolla on merkitys
const WEBSITE_STATUS_CONFIG = [
  { key: 'NO WEBSITE', bar: 'bg-status-none' },
  { key: 'BROKEN WEBSITE', bar: 'bg-status-broken' },
  { key: 'INSECURE', bar: 'bg-status-insecure' },
  { key: 'NOT MOBILE', bar: 'bg-status-mobile' },
  { key: 'WEBSITE OK', bar: 'bg-status-ok' },
  { key: 'UNKNOWN', bar: 'bg-status-unknown' },
] as const;

const panelClass = 'bg-surface rounded border border-line p-card';
const panelTitle = 'text-sm font-semibold text-fg mb-3.5';

const DashboardView: React.FC = () => {
  const { savedAgencies, loading } = usePipeline();

  if (loading) {
    return (
      <section className="space-y-5">
        <div className="h-6 w-40 bg-raised rounded-sm animate-pulse" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-24 bg-surface border border-line rounded animate-pulse" />
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
    <section className="space-y-5">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="text-xl font-semibold tracking-tight text-fg">Dashboard</h1>
        <p className="text-sm text-fg-subtle">
          Overview of your pipeline performance and lead quality
        </p>
      </header>

      {total === 0 ? (
        <div className="p-12 text-center border border-dashed border-line-strong rounded">
          <p className="text-fg font-medium mb-1">No data yet</p>
          <p className="text-sm text-fg-subtle">
            Save leads to your pipeline to see analytics here
          </p>
        </div>
      ) : (
        <>
          {/* KPI Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KpiCard label="Total leads" value={total} icon={Users} />
            <KpiCard label="Opportunities" value={opportunityCount} icon={TrendingUp} />
            <KpiCard label="Contacted+" value={`${conversionRate}%`} icon={CheckCircle2} />
            <KpiCard label="Hired" value={stageCounts['Hired']} icon={Users} />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {/* Pipeline Funnel */}
            <div className={panelClass}>
              <h2 className={panelTitle}>Pipeline funnel</h2>
              <div className="space-y-2.5">
                {PIPELINE_STATUSES.map((status) => {
                  const count = stageCounts[status];
                  const pct = total > 0 ? (count / total) * 100 : 0;
                  return (
                    <div key={status} className="flex items-center gap-3">
                      <span className="w-32 shrink-0 text-sm text-fg-muted">{status}</span>
                      <div className="flex-1 h-1.5 bg-raised rounded-sm overflow-hidden">
                        <motion.div
                          initial={{ width: 0 }}
                          animate={{ width: `${pct}%` }}
                          transition={{ duration: 0.6, ease: 'easeOut' }}
                          className="h-full bg-fg-muted"
                        />
                      </div>
                      <span className="w-8 text-right text-sm font-medium tabular-nums text-fg">
                        {count}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Website Status Breakdown */}
            <div className={panelClass}>
              <h2 className={panelTitle}>Website status</h2>
              <div className="space-y-2.5">
                {websiteCounts.map((ws) => {
                  const pct = total > 0 ? Math.round((ws.count / total) * 100) : 0;
                  return (
                    <div key={ws.key} className="flex items-center gap-3">
                      <span className="w-32 shrink-0">
                        <StatusBadge status={ws.key} />
                      </span>
                      <div className="flex-1 h-1.5 bg-raised rounded-sm overflow-hidden">
                        <div className={`h-full ${ws.bar}`} style={{ width: `${pct}%` }} />
                      </div>
                      <span className="w-8 text-right text-sm font-medium tabular-nums text-fg">{ws.count}</span>
                      <span className="w-9 text-right text-xs tabular-nums text-fg-subtle">{pct}%</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Recent Activity */}
          <div className="bg-surface rounded border border-line">
            <h2 className="px-card pt-card pb-2 text-sm font-semibold text-fg">Recently added</h2>
            <div className="divide-y divide-line">
              {savedAgencies.slice(0, 8).map((a) => (
                <div key={a.id} className="flex items-center justify-between gap-4 px-card py-2.5">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-fg truncate">{a.name}</p>
                    <p className="text-xs text-fg-subtle">{a.city}</p>
                  </div>
                  <div className="flex items-center gap-5 shrink-0">
                    {a.website_status && <StatusBadge status={a.website_status} />}
                    <span className="w-32 text-right text-xs text-fg-muted">
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
}

const KpiCard: React.FC<KpiCardProps> = ({ label, value, icon: Icon }) => (
  <motion.div
    initial={{ opacity: 0, y: 10 }}
    animate={{ opacity: 1, y: 0 }}
    className="bg-surface rounded border border-line p-card"
  >
    <div className="flex items-center justify-between text-fg-subtle">
      <p className="text-xs font-medium">{label}</p>
      <Icon size={14} />
    </div>
    <p className="mt-2 text-2xl font-semibold tracking-tight tabular-nums text-fg">{value}</p>
  </motion.div>
);

export default DashboardView;
