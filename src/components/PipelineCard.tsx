import React, { useState } from 'react';
import { motion } from 'framer-motion';
import {
  ExternalLink,
  MapPin,
  Phone,
  Trash2,
  Globe,
  Building2,
  Sparkles,
  ChevronLeft,
  ChevronRight,
  Mail,
  Search,
  Loader2,
} from 'lucide-react';
import { toast } from 'sonner';
import { usePipeline } from '../context/PipelineContext';
import { PIPELINE_STATUSES } from '../types/agency';
import type { SavedAgency, PipelineStatus } from '../types/agency';
import EmailDraftModal from './EmailDraftModal';
import { ScoreBadge, RatingDisplay } from './ScoreBadge';

interface PipelineCardProps {
  agency: SavedAgency;
  selected: boolean;
  onToggleSelect: (id: number) => void;
  onStatusChange: (id: number, status: PipelineStatus) => void;
  onNotesChange: (id: number, notes: string) => void;
  onRemove: (id: number) => void;
}

const PipelineCard: React.FC<PipelineCardProps> = ({
  agency,
  selected,
  onToggleSelect,
  onStatusChange,
  onNotesChange,
  onRemove,
}) => {
  const [notesDraft, setNotesDraft] = useState(agency.notes ?? '');
  const [isExpanded, setIsExpanded] = useState(false);
  const [emailModalOpen, setEmailModalOpen] = useState(false);
  const [findingEmail, setFindingEmail] = useState(false);
  const { findEmail } = usePipeline();

  // Sama ehto kuin backendin EMAIL_SEARCH_STATUSES
  const canSearchEmail =
    !!agency.website &&
    ['WEBSITE OK', 'NOT MOBILE', 'INSECURE'].includes(agency.website_status ?? '');

  const handleFindEmail = async () => {
    setFindingEmail(true);
    try {
      const updated = await findEmail(agency.id);
      if (updated.email) {
        toast.success(`Found ${updated.email}`);
      } else {
        toast.info('No email address found on the website');
      }
    } catch {
      toast.error('Email search failed');
    } finally {
      setFindingEmail(false);
    }
  };

  const handleNotesBlur = () => {
    if (notesDraft !== (agency.notes ?? '')) {
      onNotesChange(agency.id, notesDraft);
    }
  };

  const website = agency.website
    ? agency.website.startsWith('http')
      ? agency.website
      : `http://${agency.website}`
    : '';

  const getStatusColor = (status: string) => {
    if (status === 'NO WEBSITE')
      return 'bg-rose-50 text-rose-700 border-rose-200';
    if (status === 'BROKEN WEBSITE')
      return 'bg-orange-50 text-orange-700 border-orange-200';
    if (status === 'INSECURE')
      return 'bg-amber-50 text-amber-700 border-amber-200';
    if (status === 'NOT MOBILE')
      return 'bg-yellow-50 text-yellow-700 border-yellow-200';
    if (status === 'WEBSITE OK')
      return 'bg-emerald-50 text-emerald-700 border-emerald-200';
    return 'bg-slate-50 text-slate-700 border-slate-200';
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`bg-white rounded-xl border-2 shadow-sm hover:shadow-md transition-all duration-200 overflow-hidden ${
        selected ? 'border-indigo-400 ring-2 ring-indigo-100' : 'border-slate-200'
      }`}
    >
      {/* Header Section */}
      <div className="p-5 border-b border-slate-100 bg-gradient-to-r from-slate-50 to-white">
        <div className="flex items-start justify-between gap-3 mb-3">
          <label className="flex items-center shrink-0 cursor-pointer pt-0.5">
            <input
              type="checkbox"
              checked={selected}
              onChange={() => onToggleSelect(agency.id)}
              className="w-4 h-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
            />
          </label>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <Building2 size={16} className="text-indigo-600 shrink-0" />
              <h4 className="text-base font-bold text-slate-900 truncate">
                {agency.name}
              </h4>
            </div>
            <p className="flex items-center gap-2 text-sm text-slate-600">
              <MapPin size={14} className="shrink-0 text-slate-400" />
              <span className="truncate">{agency.address}</span>
            </p>
          </div>
          <button
            onClick={() => onRemove(agency.id)}
            className="shrink-0 p-2 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors"
            aria-label="Remove from pipeline"
          >
            <Trash2 size={16} />
          </button>
        </div>

        {/* Score, Website Status ja Rating */}
        <div className="flex flex-wrap items-center gap-2">
          <ScoreBadge score={agency.lead_score} />
          {agency.website_status && (
            <span
              title={agency.website_issue ?? undefined}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold border ${getStatusColor(
                agency.website_status,
              )}`}
            >
              {agency.website_status}
            </span>
          )}
          <RatingDisplay rating={agency.rating} reviewCount={agency.review_count} />
        </div>
        {agency.website_issue && (
          <p className="mt-2 text-xs text-slate-500">{agency.website_issue}</p>
        )}
      </div>

      {/* Contact Info Section */}
      <div className="p-5 space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          {agency.phone ? (
            <a
              href={`tel:${agency.phone}`}
              className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-50 hover:bg-indigo-50 text-slate-700 hover:text-indigo-700 transition-colors text-sm font-medium"
            >
              <Phone size={14} className="shrink-0" />
              <span>{agency.phone}</span>
            </a>
          ) : (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-50 text-slate-400 text-sm">
              <Phone size={14} className="shrink-0" />
              <span>No phone</span>
            </div>
          )}

          {website ? (
            <a
              href={website}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 px-3 py-2 rounded-lg bg-indigo-50 hover:bg-indigo-100 text-indigo-700 hover:text-indigo-800 transition-colors text-sm font-medium"
            >
              <Globe size={14} className="shrink-0" />
              <span className="truncate max-w-[140px]">Visit Website</span>
              <ExternalLink size={12} className="shrink-0" />
            </a>
          ) : (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-50 text-slate-400 text-sm">
              <Globe size={14} className="shrink-0" />
              <span>No website</span>
            </div>
          )}
        </div>

        {/* Email */}
        <div className="flex flex-wrap items-center gap-2">
          {agency.email ? (
            <a
              href={`mailto:${agency.email}`}
              title={agency.email_source ? `Found: ${agency.email_source}` : undefined}
              className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-50 hover:bg-indigo-50 text-slate-700 hover:text-indigo-700 transition-colors text-sm font-medium min-w-0"
            >
              <Mail size={14} className="shrink-0" />
              <span className="truncate">{agency.email}</span>
            </a>
          ) : (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-50 text-slate-400 text-sm">
              <Mail size={14} className="shrink-0" />
              <span>No email</span>
            </div>
          )}
          {canSearchEmail && (
            <button
              type="button"
              onClick={handleFindEmail}
              disabled={findingEmail}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium text-indigo-700 bg-indigo-50 hover:bg-indigo-100 transition-colors disabled:opacity-60"
            >
              {findingEmail ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />}
              {findingEmail ? 'Searching...' : agency.email ? 'Search again' : 'Find email'}
            </button>
          )}
        </div>
        {agency.email && agency.email_source && (
          <p className="-mt-1 text-[11px] text-slate-400">Source: {agency.email_source}</p>
        )}

        {/* Pipeline Stage Navigation */}
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-2 uppercase tracking-wide">
            Pipeline Stage
          </label>
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                const i = PIPELINE_STATUSES.indexOf(agency.pipeline_status);
                if (i > 0) onStatusChange(agency.id, PIPELINE_STATUSES[i - 1]);
              }}
              disabled={PIPELINE_STATUSES.indexOf(agency.pipeline_status) === 0}
              className="p-2 rounded-lg border-2 border-slate-200 text-slate-600 hover:border-indigo-300 hover:text-indigo-700 transition-colors disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:border-slate-200 disabled:hover:text-slate-600"
              aria-label="Previous stage"
            >
              <ChevronLeft size={16} />
            </button>
            <span className="flex-1 text-center text-sm font-semibold text-slate-700 py-2 bg-slate-50 rounded-lg border-2 border-slate-200">
              {agency.pipeline_status}
            </span>
            <button
              onClick={() => {
                const i = PIPELINE_STATUSES.indexOf(agency.pipeline_status);
                if (i < PIPELINE_STATUSES.length - 1) onStatusChange(agency.id, PIPELINE_STATUSES[i + 1]);
              }}
              disabled={PIPELINE_STATUSES.indexOf(agency.pipeline_status) === PIPELINE_STATUSES.length - 1}
              className="p-2 rounded-lg border-2 border-slate-200 text-slate-600 hover:border-indigo-300 hover:text-indigo-700 transition-colors disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:border-slate-200 disabled:hover:text-slate-600"
              aria-label="Next stage"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>

        {/* Notes Section */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide">
              Notes
            </label>
            {notesDraft && (
              <button
                onClick={() => setIsExpanded(!isExpanded)}
                className="text-xs text-indigo-600 hover:text-indigo-700 font-medium"
              >
                {isExpanded ? 'Collapse' : 'Expand'}
              </button>
            )}
          </div>
          <textarea
            value={notesDraft}
            onChange={(e) => setNotesDraft(e.target.value)}
            onBlur={handleNotesBlur}
            rows={isExpanded ? 6 : 3}
            placeholder="Add meeting notes, follow-ups, or impressions..."
            className="w-full text-sm border-2 border-slate-200 rounded-lg px-4 py-3 text-slate-700 resize-none focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 transition-colors"
          />
        </div>

        {/* AI Draft Button */}
        <button
          onClick={() => setEmailModalOpen(true)}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium text-purple-700 bg-gradient-to-r from-purple-50 to-indigo-50 hover:from-purple-100 hover:to-indigo-100 border-2 border-purple-200 hover:border-purple-300 rounded-lg transition-all"
        >
          <Sparkles size={15} />
          AI Draft
        </button>
      </div>

      {/* Email Modal */}
      <EmailDraftModal
        isOpen={emailModalOpen}
        onClose={() => setEmailModalOpen(false)}
        agency={agency}
      />
    </motion.div>
  );
};

export default PipelineCard;
