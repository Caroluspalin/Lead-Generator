import React, { useState } from 'react';
import { motion } from 'framer-motion';
import {
  ExternalLink,
  Trash2,
  Sparkles,
  ChevronLeft,
  ChevronRight,
  Loader2,
  PhoneCall,
  Ban,
  LayoutTemplate,
  XCircle,
  Rocket,
  RefreshCw,
  Eye,
} from 'lucide-react';
import { toast } from 'sonner';
import { usePipeline } from '../context/PipelineContext';
import { apiFetch } from '../lib/api';
import { outreachErrorMessage, readDetail } from '../lib/apiErrors';
import { formatEur } from '../lib/money';
import { PIPELINE_STATUSES } from '../types/agency';
import type { SavedAgency, PipelineStatus } from '../types/agency';
import EmailDraftModal from './EmailDraftModal';
import CallScriptModal from './CallScriptModal';
import DemoModal from './DemoModal';
import { ScoreBadge, RatingDisplay, StatusBadge } from './ScoreBadge';

const MAX_AMOUNT = 1_000_000;

interface AmountRowProps {
  label: string;
  suffix?: string;
  value: number | null | undefined;
  ariaLabel: string;
  onSave: (next: number | null) => Promise<void>;
}

// Edit -> Save kuten Website-rivi: Enter tallentaa, Esc peruu, tyhjä = ei arvoa
const AmountRow: React.FC<AmountRowProps> = ({ label, suffix = '', value, ariaLabel, onSave }) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const linkClass =
    'rounded-sm underline decoration-fg-subtle/40 underline-offset-2 hover:decoration-fg transition-colors';

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    let next: number | null = null;
    if (text) {
      if (!/^\d+$/.test(text) || Number(text) > MAX_AMOUNT) {
        toast.error(`Enter a whole number between 0 and ${formatEur(MAX_AMOUNT)}`);
        return;
      }
      next = Number(text);
    }
    if (next === (value ?? null)) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(next);
      setEditing(false);
    } catch {
      toast.error(`Failed to save ${label.toLowerCase()}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <dt className="text-fg-subtle">{label}</dt>
      <dd className="min-w-0">
        {editing ? (
          <form onSubmit={handleSave} className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            <input
              type="text"
              inputMode="numeric"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') setEditing(false);
              }}
              autoFocus
              maxLength={7}
              placeholder="€"
              aria-label={ariaLabel}
              className="w-24 min-w-0 h-control-sm px-2 font-mono text-xs bg-canvas border border-line rounded text-fg"
            />
            <button
              type="submit"
              disabled={saving}
              className={`inline-flex items-center gap-1 text-xs text-fg disabled:opacity-60 ${linkClass}`}
            >
              {saving && <Loader2 size={11} className="animate-spin" />}
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              disabled={saving}
              className={`text-xs text-fg-muted hover:text-fg ${linkClass}`}
            >
              Cancel
            </button>
          </form>
        ) : (
          <>
            {value != null ? (
              <span className="text-xs text-fg tabular-nums">
                {formatEur(value)}
                {suffix}
              </span>
            ) : (
              <span className="text-fg-subtle">None</span>
            )}
            <button
              type="button"
              onClick={() => {
                setDraft(value != null ? String(value) : '');
                setEditing(true);
              }}
              className={`ml-2.5 text-xs text-fg-muted hover:text-fg ${linkClass}`}
            >
              Edit
            </button>
          </>
        )}
      </dd>
    </>
  );
};

interface PipelineCardProps {
  agency: SavedAgency;
  selected: boolean;
  onToggleSelect: (id: number) => void;
  onStatusChange: (id: number, status: PipelineStatus) => void;
  onNotesChange: (id: number, notes: string) => void;
  onRemove: (id: number) => void;
  onDismiss: (agency: SavedAgency) => void;
}

// Backend palauttaa UTC-ajan; tänään pelkkä kellonaika, muuten päivä + kellonaika
function formatOpenTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const date = new Date(/(?:Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`);
  const time = date.toLocaleTimeString('fi-FI', { hour: '2-digit', minute: '2-digit' });
  return date.toDateString() === new Date().toDateString()
    ? time
    : `${date.toLocaleDateString('fi-FI', { day: 'numeric', month: 'numeric' })} ${time}`;
}

const PipelineCard: React.FC<PipelineCardProps> = ({
  agency,
  selected,
  onToggleSelect,
  onStatusChange,
  onNotesChange,
  onRemove,
  onDismiss,
}) => {
  const [notesDraft, setNotesDraft] = useState(agency.notes ?? '');
  // Käsin lisätyllä liidillä ei ole Googlen paikkaa, jota hakutuloksista voisi hylätä
  const canDismiss = Boolean(agency.google_place_id && !agency.google_place_id.startsWith('manual-'));
  const [isExpanded, setIsExpanded] = useState(false);
  const [emailModalOpen, setEmailModalOpen] = useState(false);
  const [findingEmail, setFindingEmail] = useState(false);
  const [callScriptOpen, setCallScriptOpen] = useState(false);
  const [demoOpen, setDemoOpen] = useState(false);
  const [preparingDemo, setPreparingDemo] = useState(false);
  // true kun sähköposti avataan "Publish & create email" -ketjusta: backend vaatii julkaistun demon
  const [emailWithDemo, setEmailWithDemo] = useState(false);

  // Olemassa oleva demo avataan suoraan (ei uutta generointia = ei turhia API-kutsuja)
  const handleDemoEmail = async () => {
    setPreparingDemo(true);
    try {
      const existing = await apiFetch(`/leads/${agency.id}/demo`);
      if (existing.ok) {
        setDemoOpen(true);
        return;
      }
      if (existing.status !== 404) {
        toast.error(outreachErrorMessage(existing.status, await readDetail(existing)));
        return;
      }
      const res = await apiFetch(`/leads/${agency.id}/demo`, { method: 'POST', body: JSON.stringify({}) });
      if (!res.ok) {
        toast.error(outreachErrorMessage(res.status, await readDetail(res)));
        return;
      }
      setDemoOpen(true);
    } catch {
      toast.error('Failed to prepare the demo. Is the backend running?');
    } finally {
      setPreparingDemo(false);
    }
  };

  const openEmailWithDemo = () => {
    setDemoOpen(false);
    setEmailWithDemo(true);
    setEmailModalOpen(true);
  };
  const { findEmail, setDoNotContact, runAutodemo, markReviewed, refreshTimma, updateWebsite, updateDealAmounts } = usePipeline();
  const [autodemoRunning, setAutodemoRunning] = useState(false);
  const [timmaRefreshing, setTimmaRefreshing] = useState(false);
  const [editingWebsite, setEditingWebsite] = useState(false);
  const [websiteDraft, setWebsiteDraft] = useState('');
  const [savingWebsite, setSavingWebsite] = useState(false);
  // Sama ehto kuin backendin timma_source(): yrityssivu tai varaa.timma.fi-varaussivu, ei /pro/-markkinointisivuja
  const isTimmaPage = (url: string | null | undefined) =>
    /^https:\/\/timma\.fi\/yritys\/[a-z0-9-]+\/?(\?.*)?$/.test(url ?? '') ||
    /^https?:\/\/varaa\.timma\.fi\/(reservation\/)?[a-z0-9-]+\/?(\?.*)?$/.test(url ?? '');
  const hasTimmaPage = isTimmaPage(agency.website);

  const startEditWebsite = () => {
    setWebsiteDraft(agency.website ?? '');
    setEditingWebsite(true);
  };

  const handleSaveWebsite = async (e: React.FormEvent) => {
    e.preventDefault();
    const next = websiteDraft.trim() || null;
    if (next === (agency.website ?? null)) {
      setEditingWebsite(false);
      return;
    }
    setSavingWebsite(true);
    try {
      const updated = await updateWebsite(agency.id, next);
      setEditingWebsite(false);
      toast.success(
        isTimmaPage(updated.website)
          ? 'Website saved. Timma page detected: Refresh Timma or Autodemo uses it.'
          : 'Website saved',
      );
    } catch {
      toast.error('Failed to save the website');
    } finally {
      setSavingWebsite(false);
    }
  };

  // Generoi + julkaisee demon (Timma-tiedoilla jos on). Ei sähköpostia: liidi jää tarkistettavaksi.
  const handleAutodemo = async () => {
    if (!window.confirm('Generate and publish a demo now? An existing demo is regenerated and its manual edits are replaced. No email is sent.')) return;
    setAutodemoRunning(true);
    try {
      const demo = await runAutodemo(agency.id);
      toast.success(`Demo published${demo.public_url ? `: ${demo.public_url}` : ''}. Review it before contacting.`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Autodemo failed');
    } finally {
      setAutodemoRunning(false);
    }
  };

  const handleMarkReviewed = async () => {
    try {
      await markReviewed(agency.id);
      toast.success('Marked as reviewed');
    } catch {
      toast.error('Failed to update review status');
    }
  };

  const handleRefreshTimma = async () => {
    setTimmaRefreshing(true);
    try {
      await refreshTimma(agency.id);
      toast.success('Timma details refreshed. Regenerate the demo to use them.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Timma refresh failed');
    } finally {
      setTimmaRefreshing(false);
    }
  };

  const handleToggleDoNotContact = async () => {
    const next = !agency.do_not_contact;
    try {
      await setDoNotContact(agency.id, next);
      toast.success(next ? `${agency.name} marked do not contact` : `${agency.name} can be contacted again`);
    } catch {
      toast.error('Failed to update contact status');
    }
  };

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

  // Käsin lisätty osoite voi olla mitä tahansa: näytetään hostname jos se parsiutuu
  const websiteLabel = (() => {
    if (!website) return '';
    try {
      return new URL(website).hostname.replace('www.', '');
    } catch {
      return agency.website ?? '';
    }
  })();

  const linkClass =
    'rounded-sm underline decoration-fg-subtle/40 underline-offset-2 hover:decoration-fg transition-colors';
  const actionClass =
    'flex-1 min-w-0 inline-flex items-center justify-center gap-1.5 h-control-sm px-2 text-xs font-medium text-fg bg-raised border border-line-strong rounded hover:border-fg-subtle transition-colors disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap';
  const stageButtonClass =
    'grid size-control-sm shrink-0 place-content-center rounded border border-line-strong text-fg-muted hover:text-fg hover:bg-raised transition-colors disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-fg-muted';
  const stageIndex = PIPELINE_STATUSES.indexOf(agency.pipeline_status);

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex flex-col bg-surface rounded border p-card transition-colors ${
        selected ? 'border-fg shadow-selected-inset' : 'border-line hover:border-line-strong'
      }`}
    >
      {/* Header */}
      <div className="flex items-start gap-2.5">
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggleSelect(agency.id)}
          aria-label={`Select ${agency.name}`}
          className="mt-[3px] size-3.5 shrink-0 cursor-pointer"
        />
        <div className="flex-1 min-w-0">
          <h4 className="text-base font-medium text-fg truncate">{agency.name}</h4>
          {agency.address && <p className="text-xs text-fg-subtle truncate">{agency.address}</p>}
        </div>
        {canDismiss && (
          <button
            onClick={() => onDismiss(agency)}
            className="shrink-0 -mt-1 grid size-control-sm place-content-center rounded text-fg-subtle hover:text-fg hover:bg-raised transition-colors"
            aria-label={`Dismiss ${agency.name} permanently`}
            title="Dismiss: remove and never show in searches again"
          >
            <XCircle size={14} />
          </button>
        )}
        <button
          onClick={() => onRemove(agency.id)}
          className="shrink-0 -mr-1 -mt-1 grid size-control-sm place-content-center rounded text-fg-subtle hover:text-danger hover:bg-danger/10 transition-colors"
          aria-label="Remove from pipeline"
        >
          <Trash2 size={14} />
        </button>
      </div>

      {/* Score, sivun tila ja arvio */}
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1">
        <ScoreBadge score={agency.lead_score} />
        {agency.website_status && (
          <StatusBadge status={agency.website_status} title={agency.website_issue ?? undefined} />
        )}
        <RatingDisplay rating={agency.rating} reviewCount={agency.review_count} />
        {agency.demo_open_count ? (
          <span
            className="inline-flex items-center gap-1 rounded-sm bg-success/10 px-1.5 py-0.5 text-xs font-medium text-success"
            title="Demo opens (bots and your own previews excluded; link previews may still count)"
          >
            <Eye size={12} />
            Opened {agency.demo_open_count}× · last {formatOpenTime(agency.demo_last_opened_at)}
          </span>
        ) : null}
      </div>
      {agency.website_issue && (
        <p className="mt-1 text-xs text-fg-subtle">{agency.website_issue}</p>
      )}

      {/* Yhteystiedot */}
      <dl className="my-3 grid grid-cols-[64px_minmax(0,1fr)] gap-x-2.5 gap-y-1.5 border-y border-line py-3 text-sm">
        <dt className="text-fg-subtle">Phone</dt>
        <dd className="min-w-0 tabular-nums">
          {agency.phone ? (
            <a href={`tel:${agency.phone}`} className={`text-fg ${linkClass}`}>
              {agency.phone}
            </a>
          ) : (
            <span className="text-fg-subtle">—</span>
          )}
        </dd>

        <dt className="text-fg-subtle">Website</dt>
        <dd className="min-w-0">
          {editingWebsite ? (
            <form onSubmit={handleSaveWebsite} className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
              <input
                type="text"
                inputMode="url"
                value={websiteDraft}
                onChange={(e) => setWebsiteDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') setEditingWebsite(false);
                }}
                autoFocus
                maxLength={500}
                placeholder="https://timma.fi/yritys/…"
                aria-label={`Website of ${agency.name}`}
                className="w-full min-w-0 h-control-sm px-2 font-mono text-xs bg-canvas border border-line rounded text-fg"
              />
              <button
                type="submit"
                disabled={savingWebsite}
                className={`inline-flex items-center gap-1 text-xs text-fg disabled:opacity-60 ${linkClass}`}
              >
                {savingWebsite && <Loader2 size={11} className="animate-spin" />}
                {savingWebsite ? 'Saving…' : 'Save'}
              </button>
              <button
                type="button"
                onClick={() => setEditingWebsite(false)}
                disabled={savingWebsite}
                className={`text-xs text-fg-muted hover:text-fg ${linkClass}`}
              >
                Cancel
              </button>
            </form>
          ) : (
            <>
              {website ? (
                <a
                  href={website}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={agency.website}
                  className={`inline-flex max-w-full items-center gap-1 font-mono text-xs text-fg ${linkClass}`}
                >
                  <span className="truncate">{websiteLabel}</span>
                  <ExternalLink size={11} className="shrink-0 text-fg-subtle" />
                </a>
              ) : (
                <span className="text-fg-subtle">None</span>
              )}
              <button
                type="button"
                onClick={startEditWebsite}
                title="Edit the website address, e.g. paste the Timma business page"
                className={`ml-2.5 text-xs text-fg-muted hover:text-fg ${linkClass}`}
              >
                Edit
              </button>
            </>
          )}
          {hasTimmaPage && !editingWebsite && (
            <button
              type="button"
              onClick={handleRefreshTimma}
              disabled={timmaRefreshing}
              title={agency.timma_fetched_at ? `Timma details fetched ${new Date(agency.timma_fetched_at).toLocaleDateString()}` : 'Timma details not fetched yet'}
              className={`ml-2.5 inline-flex items-center gap-1 text-xs text-fg-muted hover:text-fg disabled:opacity-60 ${linkClass}`}
            >
              <RefreshCw size={11} className={timmaRefreshing ? 'animate-spin' : ''} />
              {timmaRefreshing ? 'Refreshing…' : 'Refresh Timma'}
            </button>
          )}
        </dd>

        {agency.pipeline_status !== 'Rejected' && (
          <AmountRow
            label="Value"
            value={agency.deal_value}
            ariaLabel={`Deal value of ${agency.name} in euros`}
            onSave={async (next) => {
              await updateDealAmounts(agency.id, { deal_value: next });
            }}
          />
        )}
        {agency.pipeline_status === 'Hired' && (
          <AmountRow
            label="Maintenance"
            suffix="/mo"
            value={agency.recurring_monthly}
            ariaLabel={`Monthly maintenance of ${agency.name} in euros`}
            onSave={async (next) => {
              await updateDealAmounts(agency.id, { recurring_monthly: next });
            }}
          />
        )}

        <dt className="text-fg-subtle">Email</dt>
        <dd className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-0.5">
            {agency.email ? (
              <a
                href={`mailto:${agency.email}`}
                title={agency.email_source ? `Found: ${agency.email_source}` : undefined}
                className={`min-w-0 truncate text-fg ${linkClass}`}
              >
                {agency.email}
              </a>
            ) : (
              <span className="text-fg-subtle">None found</span>
            )}
            {canSearchEmail && (
              <button
                type="button"
                onClick={handleFindEmail}
                disabled={findingEmail}
                className={`inline-flex items-center gap-1 text-fg-muted hover:text-fg disabled:opacity-60 ${linkClass}`}
              >
                {findingEmail && <Loader2 size={12} className="animate-spin" />}
                {findingEmail ? 'Searching...' : agency.email ? 'Search again' : 'Find email'}
              </button>
            )}
          </div>
          {agency.email && agency.email_source && (
            <p className="mt-0.5 text-2xs text-fg-subtle">Source: {agency.email_source}</p>
          )}
        </dd>
      </dl>

      {/* Pipeline Stage Navigation */}
      <div className="flex items-center gap-1.5" role="group" aria-label="Pipeline stage">
        <button
          onClick={() => {
            if (stageIndex > 0) onStatusChange(agency.id, PIPELINE_STATUSES[stageIndex - 1]);
          }}
          disabled={stageIndex === 0}
          className={stageButtonClass}
          aria-label="Previous stage"
        >
          <ChevronLeft size={14} />
        </button>
        <span className="flex-1 h-control-sm leading-[26px] text-center text-sm font-medium text-fg rounded border border-line-strong">
          {agency.pipeline_status}
        </span>
        <button
          onClick={() => {
            if (stageIndex < PIPELINE_STATUSES.length - 1) onStatusChange(agency.id, PIPELINE_STATUSES[stageIndex + 1]);
          }}
          disabled={stageIndex === PIPELINE_STATUSES.length - 1}
          className={stageButtonClass}
          aria-label="Next stage"
        >
          <ChevronRight size={14} />
        </button>
      </div>

      {/* Notes Section */}
      <div className="mt-2.5">
        <div className="mb-1 flex items-center justify-between">
          <label htmlFor={`notes-${agency.id}`} className="text-2xs font-medium text-fg-subtle">
            Notes
          </label>
          {notesDraft && (
            <button
              onClick={() => setIsExpanded(!isExpanded)}
              className={`text-2xs font-medium text-fg-muted hover:text-fg ${linkClass}`}
            >
              {isExpanded ? 'Collapse' : 'Expand'}
            </button>
          )}
        </div>
        <textarea
          id={`notes-${agency.id}`}
          value={notesDraft}
          onChange={(e) => setNotesDraft(e.target.value)}
          onBlur={handleNotesBlur}
          rows={isExpanded ? 6 : 2}
          placeholder="Meeting notes, follow-ups, impressions..."
          className="w-full text-sm bg-canvas border border-line rounded px-2.5 py-2 text-fg resize-none transition-colors"
        />
      </div>

      {agency.review_before_contact && (
        <div className="mt-2.5 flex items-center gap-2 px-2.5 py-1.5 rounded border border-warning/30 bg-warning/10 text-fg text-xs font-medium">
          <Eye size={13} className="shrink-0 text-warning" />
          <span className="flex-1">Review demo before contacting</span>
          <button onClick={handleMarkReviewed} className={`text-2xs text-fg-muted hover:text-fg ${linkClass}`}>
            Mark reviewed
          </button>
        </div>
      )}
      {/* Outreach: AI Draft + Call script + Demo (estetty jos do not contact) */}
      {agency.do_not_contact && (
        <div className="mt-2.5 flex items-center gap-2 px-2.5 py-1.5 rounded border border-danger/30 bg-danger/10 text-fg text-xs font-medium">
          <Ban size={13} className="shrink-0 text-danger" />
          Do not contact
        </div>
      )}
      <div className="mt-2.5 flex gap-1.5">
        <button
          onClick={() => setEmailModalOpen(true)}
          disabled={agency.do_not_contact}
          className={actionClass}
        >
          <Sparkles size={13} className="shrink-0" />
          AI draft
        </button>
        <button
          onClick={() => setCallScriptOpen(true)}
          disabled={agency.do_not_contact}
          className={actionClass}
        >
          <PhoneCall size={13} className="shrink-0" />
          Call script
        </button>
        <button
          onClick={handleDemoEmail}
          disabled={agency.do_not_contact || preparingDemo}
          title={agency.do_not_contact ? 'This lead is marked do not contact' : 'Demo website + email'}
          className={actionClass}
        >
          {preparingDemo ? <Loader2 size={13} className="shrink-0 animate-spin" /> : <LayoutTemplate size={13} className="shrink-0" />}
          {preparingDemo ? 'Preparing…' : 'Demo'}
        </button>
      </div>
      <div className="mt-1.5 flex">
        <button
          onClick={handleAutodemo}
          disabled={agency.do_not_contact || autodemoRunning}
          title={agency.do_not_contact ? 'This lead is marked do not contact' : 'Generate and publish a demo (Timma details if available), no email'}
          className={actionClass}
        >
          {autodemoRunning ? <Loader2 size={13} className="shrink-0 animate-spin" /> : <Rocket size={13} className="shrink-0" />}
          {autodemoRunning ? 'Publishing demo…' : 'Autodemo'}
        </button>
      </div>
      {(preparingDemo || autodemoRunning) && (
        <p role="status" className="mt-1 text-2xs text-fg-subtle text-center">
          {autodemoRunning ? 'Generating and publishing, can take ~20 s' : 'Preparing demo, can take ~10 s'}
        </p>
      )}
      <button
        onClick={handleToggleDoNotContact}
        className="mt-2 self-center rounded-sm text-2xs font-medium text-fg-subtle hover:text-fg transition-colors"
      >
        {agency.do_not_contact ? 'Allow contact again' : 'Mark do not contact'}
      </button>

      {/* Modals */}
      <EmailDraftModal
        isOpen={emailModalOpen}
        onClose={() => {
          setEmailModalOpen(false);
          setEmailWithDemo(false);
        }}
        agency={agency}
        requireDemoLink={emailWithDemo}
        onOpenCallScript={() => {
          setEmailModalOpen(false);
          setEmailWithDemo(false);
          setCallScriptOpen(true);
        }}
      />
      <CallScriptModal
        isOpen={callScriptOpen}
        onClose={() => setCallScriptOpen(false)}
        agency={agency}
      />
      <DemoModal isOpen={demoOpen} onClose={() => setDemoOpen(false)} agency={agency} onCreateEmail={openEmailWithDemo} />
    </motion.div>
  );
};

export default PipelineCard;
