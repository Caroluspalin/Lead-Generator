import React, { useMemo, useState } from 'react';
import {
  ExternalLink,
  PlusCircle,
  MapPin,
  Phone,
  Search,
  CheckCircle2,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Map as MapIcon,
  PauseCircle,
} from 'lucide-react';
import type { Agency, WebsiteStatus } from '../types/agency';
import { ScoreBadge, RatingDisplay } from './ScoreBadge';

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

const headerCell = 'px-6 py-4 font-semibold text-xs text-slate-500 uppercase tracking-wider';

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
        className={`inline-flex items-center gap-1 uppercase tracking-wider hover:text-slate-800 transition-colors ${
          isActive ? 'text-indigo-700' : ''
        }`}
      >
        {label}
        <Icon size={12} className={isActive ? '' : 'opacity-40'} />
      </button>
    </th>
  );
};

const SkeletonRow: React.FC = () => (
  <tr className="animate-pulse">
    <td className="px-6 py-4">
      <div className="h-6 w-10 bg-slate-200 rounded-lg" />
    </td>
    <td className="px-6 py-4">
      <div className="h-4 w-40 bg-slate-200 rounded mb-2" />
      <div className="h-3 w-28 bg-slate-100 rounded" />
    </td>
    <td className="px-6 py-4">
      <div className="h-4 w-16 bg-slate-200 rounded" />
    </td>
    <td className="px-6 py-4">
      <div className="h-4 w-28 bg-slate-200 rounded" />
    </td>
    <td className="px-6 py-4">
      <div className="h-4 w-32 bg-slate-200 rounded" />
    </td>
    <td className="px-6 py-4">
      <div className="h-6 w-24 bg-slate-200 rounded-full" />
    </td>
    <td className="px-6 py-4 text-right">
      <div className="h-7 w-28 bg-slate-200 rounded-lg ml-auto" />
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
      <div className="p-12 text-center text-slate-400">
        <p>No results or search error.</p>
      </div>
    );
  }

  const headers = (
    <tr className="bg-slate-50 border-b border-slate-200">
      <SortableHeader label="Score" sortKey="score" active={sortKey} dir={sortDir} onSort={handleSort} />
      <SortableHeader label="Business" sortKey="name" active={sortKey} dir={sortDir} onSort={handleSort} />
      <SortableHeader label="Rating" sortKey="rating" active={sortKey} dir={sortDir} onSort={handleSort} />
      <th className={headerCell}>Contact</th>
      <th className={headerCell}>Website</th>
      <SortableHeader label="Status" sortKey="website" active={sortKey} dir={sortDir} onSort={handleSort} />
      <th className={`${headerCell} text-right`}>Action</th>
    </tr>
  );

  if (loading) {
    return (
      <div className="w-full overflow-hidden bg-white rounded-xl shadow-sm border border-slate-200">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>{headers}</thead>
            <tbody className="divide-y divide-slate-100">
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
      <div className="p-12 text-center bg-white rounded-xl border-2 border-dashed border-slate-200">
        <Search size={32} className="mx-auto text-slate-300 mb-3" />
        <p className="text-slate-500 font-medium">No results</p>
        <p className="text-sm text-slate-400 mt-1">Search to discover businesses</p>
      </div>
    );
  }

  return (
    <div className="w-full overflow-hidden bg-white rounded-xl shadow-sm border border-slate-200">
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>{headers}</thead>
          <tbody className="divide-y divide-slate-100">
            {sortedLeads.map((lead) => (
              <tr
                key={lead.id}
                className={`hover:bg-slate-50/80 transition-colors group ${lead.already_saved ? 'bg-slate-50/60' : ''}`}
              >
                <td className="px-6 py-4">
                  <ScoreBadge score={lead.lead_score} />
                </td>

                <td className="px-6 py-4">
                  <div className="flex flex-col">
                    <span className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-semibold text-slate-900">{lead.name}</span>
                      {lead.business_status === 'CLOSED_TEMPORARILY' && (
                        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-semibold bg-slate-200 text-slate-700">
                          <PauseCircle size={10} />
                          Temporarily closed
                        </span>
                      )}
                    </span>
                    <span className="flex items-center gap-1 text-xs text-slate-500 mt-0.5">
                      <MapPin size={10} /> {lead.address}
                    </span>
                    {lead.maps_url && (
                      <a
                        href={lead.maps_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800 hover:underline mt-1 w-fit"
                      >
                        <MapIcon size={11} />
                        Google Maps
                      </a>
                    )}
                  </div>
                </td>

                <td className="px-6 py-4 whitespace-nowrap">
                  <RatingDisplay rating={lead.rating} reviewCount={lead.review_count} />
                </td>

                <td className="px-6 py-4">
                  {lead.phone ? (
                     <span className="flex items-center gap-1.5 text-sm text-slate-600 whitespace-nowrap">
                        <Phone size={12} className="text-slate-400"/> {lead.phone}
                     </span>
                  ) : (
                    <span className="text-xs text-slate-400 italic">No phone</span>
                  )}
                </td>

                <td className="px-6 py-4 text-sm text-slate-500">
                  {lead.website ? (
                    <a
                      href={lead.website.startsWith('http') ? lead.website : `http://${lead.website}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1 hover:text-indigo-600 hover:underline"
                    >
                      {new URL(lead.website.startsWith('http') ? lead.website : `http://${lead.website}`).hostname.replace('www.', '')}
                      <ExternalLink size={12} className="opacity-0 group-hover:opacity-100 transition-opacity" />
                    </a>
                  ) : (
                    <span className="text-slate-400">-</span>
                  )}
                </td>

                <td className="px-6 py-4">
                  <StatusBadge status={lead.website_status} />
                  {lead.website_issue && (
                    <span className="block text-[11px] text-slate-500 mt-1 whitespace-nowrap">
                      {lead.website_issue}
                    </span>
                  )}
                </td>

                <td className="px-6 py-4 text-right">
                  {lead.already_saved ? (
                    <span className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-100 rounded-lg whitespace-nowrap">
                      <CheckCircle2 size={14} />
                      In pipeline
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => onSaveLead && onSaveLead(lead)}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-indigo-700 bg-indigo-50 hover:bg-indigo-100 rounded-lg transition-colors disabled:opacity-60 whitespace-nowrap"
                      disabled={!onSaveLead}
                    >
                      <PlusCircle size={14} />
                      Save to Pipeline
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

// Apukomponentti tilan väreille
const StatusBadge = ({ status }: { status: string }) => {
  let styles = "bg-slate-100 text-slate-600 border-slate-200";

  if (status === "NO WEBSITE") styles = "bg-rose-50 text-rose-700 border-rose-100";
  else if (status === "BROKEN WEBSITE") styles = "bg-orange-50 text-orange-700 border-orange-100";
  else if (status === "INSECURE") styles = "bg-amber-50 text-amber-700 border-amber-100";
  else if (status === "NOT MOBILE") styles = "bg-yellow-50 text-yellow-700 border-yellow-100";
  else if (status === "WEBSITE OK") styles = "bg-emerald-50 text-emerald-700 border-emerald-100";

  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border whitespace-nowrap ${styles}`}>
      {status}
    </span>
  );
};

export default LeadTable;
