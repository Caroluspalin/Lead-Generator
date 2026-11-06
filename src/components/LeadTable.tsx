import React, { useMemo, useState } from 'react';
import {
  PlusCircle,
  Search,
  Check,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  PauseCircle,
} from 'lucide-react';
import type { Agency, WebsiteStatus } from '../types/agency';
import { ScoreBadge, RatingDisplay, StatusBadge } from './ScoreBadge';

interface LeadTableProps {
  leads: Agency[];
  loading?: boolean;
  onSaveLead?: (lead: Agency) => void;
}

type SortKey = 'score' | 'name' | 'rating' | 'reviews' | 'website';
type SortDir = 'asc' | 'desc';

// Huonoin sivu ensin, kun järjestetään laskevasti (sama järjestys kuin pisteytyksessä)
const WEBSITE_SEVERITY: Record<WebsiteStatus, number> = {
  'NO WEBSITE': 6,
  'BROKEN WEBSITE': 5,
  INSECURE: 4,
  'NOT MOBILE': 3,
  UNKNOWN: 2,
  'WEBSITE OK': 1,
};

const isWebsiteStatus = (status: string): status is WebsiteStatus => status in WEBSITE_SEVERITY;

const sortValue = (lead: Agency, key: SortKey): number | string => {
  switch (key) {
    case 'score':
      return lead.lead_score ?? -1;
    case 'name':
      return lead.name.toLowerCase();
    case 'rating':
      return lead.rating ?? -1;
    case 'reviews':
      return lead.review_count ?? 0;
    case 'website':
      return isWebsiteStatus(lead.website_status) ? WEBSITE_SEVERITY[lead.website_status] : 0;
  }
};

const compareLeads = (a: Agency, b: Agency, key: SortKey, dir: SortDir): number => {
  const va = sortValue(a, key);
  const vb = sortValue(b, key);
  const base = typeof va === 'string' && typeof vb === 'string'
    ? va.localeCompare(vb, 'fi')
    : Number(va) - Number(vb);
  const primary = dir === 'asc' ? base : -base;
  // Tasatilanteessa paras score ensin, jotta järjestys pysyy ennustettavana
  return primary !== 0 ? primary : (b.lead_score ?? -1) - (a.lead_score ?? -1);
};

const headerCell = 'px-cell-x py-2 text-2xs font-medium text-fg-subtle whitespace-nowrap';
const bodyCell = 'px-cell-x py-cell-y align-middle';
const linkClass =
  'rounded-sm underline decoration-fg-subtle/40 underline-offset-2 hover:decoration-fg transition-colors';

const SortableHeader: React.FC<{
  label: string;
  sortKey: SortKey;
  active: SortKey;
  dir: SortDir;
  onSort: (key: SortKey) => void;
  className?: string;
}> = ({ label, sortKey, active, dir, onSort, className = '' }) => {
  const isActive = active === sortKey;
  const Icon = !isActive ? ArrowUpDown : dir === 'desc' ? ArrowDown : ArrowUp;
  return (
    <th className={`${headerCell} ${className}`} aria-sort={isActive ? (dir === 'desc' ? 'descending' : 'ascending') : 'none'}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={`inline-flex items-center gap-1 rounded-sm hover:text-fg transition-colors ${
          isActive ? 'text-fg' : ''
        }`}
      >
        {label}
        <Icon size={11} className={isActive ? '' : 'opacity-60'} />
      </button>
    </th>
  );
};

const SkeletonRow: React.FC = () => (
  <tr className="animate-pulse">
    <td className={bodyCell}>
      <div className="h-4 w-12 bg-raised rounded-sm" />
    </td>
    <td className={bodyCell}>
      <div className="h-4 w-40 bg-raised rounded-sm mb-1.5" />
      <div className="h-3 w-28 bg-subtle rounded-sm" />
    </td>
    <td className={bodyCell}>
      <div className="h-4 w-16 bg-raised rounded-sm" />
    </td>
    <td className={bodyCell}>
      <div className="h-4 w-24 bg-raised rounded-sm" />
    </td>
    <td className={bodyCell}>
      <div className="h-4 w-32 bg-raised rounded-sm" />
    </td>
    <td className={bodyCell}>
      <div className="h-4 w-24 bg-raised rounded-sm" />
    </td>
    <td className={`${bodyCell} text-right`}>
      <div className="h-control-sm w-16 bg-raised rounded ml-auto" />
    </td>
  </tr>
);

const LeadTable: React.FC<LeadTableProps> = ({ leads, loading, onSaveLead }) => {
  const [sortKey, setSortKey] = useState<SortKey>('score');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const sortedLeads = useMemo(
    () => (Array.isArray(leads) ? [...leads].sort((a, b) => compareLeads(a, b, sortKey, sortDir)) : []),
    [leads, sortKey, sortDir],
  );

  const handleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortKey(key);
      // Nimi aakkosjärjestyksessä, muut "paras ensin"
      setSortDir(key === 'name' ? 'asc' : 'desc');
    }
  };

  if (!leads || !Array.isArray(leads)) {
    return (
      <div className="p-12 text-center text-fg-subtle">
        <p>No results or search error.</p>
      </div>
    );
  }

  const headers = (
    <tr className="bg-canvas border-b border-line">
      <SortableHeader label="Score" sortKey="score" active={sortKey} dir={sortDir} onSort={handleSort} />
      <SortableHeader label="Business" sortKey="name" active={sortKey} dir={sortDir} onSort={handleSort} />
      <SortableHeader label="Rating" sortKey="rating" active={sortKey} dir={sortDir} onSort={handleSort} />
      <th className={headerCell}>Phone</th>
      <th className={headerCell}>Website</th>
      <SortableHeader label="Status" sortKey="website" active={sortKey} dir={sortDir} onSort={handleSort} />
      <th className={`${headerCell} text-right`}>
        <span className="sr-only">Action</span>
      </th>
    </tr>
  );

  if (loading) {
    return (
      <div className="w-full overflow-hidden bg-surface rounded border border-line">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>{headers}</thead>
            <tbody className="divide-y divide-line">
              {Array.from({ length: 5 }).map((_, i) => (
                <SkeletonRow key={i} />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  if (leads.length === 0) {
    return (
      <div className="p-12 text-center rounded border border-dashed border-line-strong">
        <Search size={24} className="mx-auto text-fg-subtle mb-3" />
        <p className="text-fg font-medium">No results</p>
        <p className="text-sm text-fg-subtle mt-1">Search to discover businesses</p>
      </div>
    );
  }

  return (
    <div className="w-full overflow-hidden bg-surface rounded border border-line">
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>{headers}</thead>
          <tbody className="divide-y divide-line">
            {sortedLeads.map((lead) => (
              <tr key={lead.id} className="hover:bg-subtle transition-colors">
                <td className={bodyCell}>
                  <ScoreBadge score={lead.lead_score} />
                </td>

                <td className={bodyCell}>
                  <div className="flex flex-col">
                    <span className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium text-fg [overflow-wrap:anywhere]">{lead.name}</span>
                      {lead.business_status === 'CLOSED_TEMPORARILY' && (
                        <span className="inline-flex items-center gap-1 px-1.5 rounded-sm border border-line-strong text-2xs font-medium text-fg-muted whitespace-nowrap">
                          <PauseCircle size={10} />
                          Temporarily closed
                        </span>
                      )}
                    </span>
                    <span className="text-xs text-fg-subtle mt-0.5 [overflow-wrap:anywhere]">
                      {lead.address}
                      {lead.maps_url && (
                        <>
                          {' · '}
                          <a
                            href={lead.maps_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className={`text-fg-muted hover:text-fg ${linkClass}`}
                          >
                            Maps
                          </a>
                        </>
                      )}
                    </span>
                  </div>
                </td>

                <td className={`${bodyCell} whitespace-nowrap`}>
                  <RatingDisplay rating={lead.rating} reviewCount={lead.review_count} />
                </td>

                <td className={`${bodyCell} whitespace-nowrap`}>
                  {lead.phone ? (
                    <span className="text-sm text-fg tabular-nums">{lead.phone}</span>
                  ) : (
                    <span className="text-xs text-fg-subtle italic">No phone</span>
                  )}
                </td>

                <td className={bodyCell}>
                  {lead.website ? (
                    <a
                      href={lead.website.startsWith('http') ? lead.website : `http://${lead.website}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      title={lead.website}
                      // Pitkä hostname ei saa levittää taulukkoa vaakavieritykseen
                      className={`block truncate max-w-[10rem] font-mono text-xs text-fg-muted hover:text-fg ${linkClass}`}
                    >
                      {new URL(lead.website.startsWith('http') ? lead.website : `http://${lead.website}`).hostname.replace('www.', '')}
                    </a>
                  ) : (
                    <span className="text-fg-subtle">—</span>
                  )}
                </td>

                <td className={bodyCell}>
                  <StatusBadge status={lead.website_status} />
                  {lead.website_issue && (
                    <span className="block text-xs text-fg-subtle mt-0.5 max-w-[10rem]">
                      {lead.website_issue}
                    </span>
                  )}
                </td>

                <td className={`${bodyCell} text-right`}>
                  {lead.already_saved ? (
                    <span className="inline-flex items-center gap-1.5 text-xs text-fg-subtle whitespace-nowrap">
                      <Check size={13} />
                      In pipeline
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => onSaveLead && onSaveLead(lead)}
                      aria-label={`Save ${lead.name} to pipeline`}
                      className="inline-flex items-center gap-1.5 h-control-sm px-2.5 text-xs font-medium text-fg border border-line-strong rounded hover:bg-raised transition-colors disabled:opacity-60 whitespace-nowrap"
                      disabled={!onSaveLead}
                    >
                      <PlusCircle size={13} />
                      Save
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default LeadTable;
