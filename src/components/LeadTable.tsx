import React from 'react';
import { ExternalLink, PlusCircle, MapPin, Phone, Search } from 'lucide-react';
import type { Agency } from '../types/agency';

interface LeadTableProps {
  leads: Agency[];
  loading?: boolean;
  onSaveLead?: (lead: Agency) => void;
}

const SkeletonRow: React.FC = () => (
  <tr className="animate-pulse">
    <td className="px-6 py-4">
      <div className="h-4 w-40 bg-slate-200 rounded mb-2" />
      <div className="h-3 w-28 bg-slate-100 rounded" />
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
  if (!leads || !Array.isArray(leads)) {
    return (
      <div className="p-12 text-center text-slate-400">
        <p>No results or search error.</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="w-full overflow-hidden bg-white rounded-xl shadow-sm border border-slate-200">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="px-6 py-4 font-semibold text-xs text-slate-500 uppercase tracking-wider">Business</th>
                <th className="px-6 py-4 font-semibold text-xs text-slate-500 uppercase tracking-wider">Contact</th>
                <th className="px-6 py-4 font-semibold text-xs text-slate-500 uppercase tracking-wider">Website</th>
                <th className="px-6 py-4 font-semibold text-xs text-slate-500 uppercase tracking-wider">Status</th>
                <th className="px-6 py-4 text-right font-semibold text-xs text-slate-500 uppercase tracking-wider">Action</th>
              </tr>
            </thead>
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
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="px-6 py-4 font-semibold text-xs text-slate-500 uppercase tracking-wider">Business</th>
              <th className="px-6 py-4 font-semibold text-xs text-slate-500 uppercase tracking-wider">Contact</th>
              <th className="px-6 py-4 font-semibold text-xs text-slate-500 uppercase tracking-wider">Website</th>
              <th className="px-6 py-4 font-semibold text-xs text-slate-500 uppercase tracking-wider">Status</th>
              <th className="px-6 py-4 text-right font-semibold text-xs text-slate-500 uppercase tracking-wider">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {leads.map((lead) => (
              <tr key={lead.id} className="hover:bg-slate-50/80 transition-colors group">
                <td className="px-6 py-4">
                  <div className="flex flex-col">
                    <span className="text-sm font-semibold text-slate-900">{lead.name}</span>
                    <span className="flex items-center gap-1 text-xs text-slate-500 mt-0.5">
                      <MapPin size={10} /> {lead.address}
                    </span>
                  </div>
                </td>
                
                <td className="px-6 py-4">
                  {lead.phone ? (
                     <span className="flex items-center gap-1.5 text-sm text-slate-600">
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
                </td>

                <td className="px-6 py-4 text-right">
                  <button
                    type="button"
                    onClick={() => onSaveLead && onSaveLead(lead)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-indigo-700 bg-indigo-50 hover:bg-indigo-100 rounded-lg transition-colors disabled:opacity-60"
                    disabled={!onSaveLead}
                  >
                    <PlusCircle size={14} />
                    Save to Pipeline
                  </button>
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
  else if (status === "NOT MOBILE") styles = "bg-yellow-50 text-yellow-700 border-yellow-100";
  else if (status === "WEBSITE OK") styles = "bg-emerald-50 text-emerald-700 border-emerald-100";

  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${styles}`}>
      {status}
    </span>
  );
};

export default LeadTable;