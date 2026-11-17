import React, { useCallback, useEffect, useState } from 'react';
import { CalendarClock, Check, Loader2, MailPlus, OctagonX, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import type { FollowUpSequence, FollowUpStep, SavedAgency } from '../types/agency';
import { apiFetch } from '../lib/api';
import { outreachErrorMessage, readDetail } from '../lib/apiErrors';
import { formatFollowUpDay } from '../lib/followUps';

interface FollowUpsPanelProps {
  agency: SavedAgency;
  // Sarjan tila muuttui: päivittää kortin
  onChanged: () => void;
}

const STEP_DAYS: Record<number, number> = { 1: 3, 2: 8 };

const buttonClass =
  'inline-flex items-center justify-center gap-2 h-control px-3 text-sm font-medium text-fg border border-line-strong hover:bg-raised rounded transition-colors whitespace-nowrap disabled:opacity-60';

const FollowUpsPanel: React.FC<FollowUpsPanelProps> = ({ agency, onChanged }) => {
  const [sequence, setSequence] = useState<FollowUpSequence | null>(null);
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<'load' | 'generate' | 'approve' | 'stop' | null>('load');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch(`/leads/${agency.id}/followups`);
        if (!cancelled && res.ok) setSequence(await res.json());
      } catch {
        // Paneeli jää tyhjäksi: luonnoksen lähetys ei riipu siitä
      } finally {
        if (!cancelled) setBusy(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [agency.id]);

  const fail = useCallback(async (res: Response, fallback: string) => {
    const detail = await readDetail(res);
    toast.error(detail || outreachErrorMessage(res.status, detail) || fallback);
  }, []);

  const generate = async () => {
    setBusy('generate');
    try {
      const res = await apiFetch(`/leads/${agency.id}/followups/generate`, { method: 'POST', body: JSON.stringify({}) });
      if (!res.ok) return fail(res, 'Could not write follow-ups');
      setSequence(await res.json());
      setEdits({});
      onChanged();
    } catch {
      toast.error('Could not reach the backend.');
    } finally {
      setBusy(null);
    }
  };

  const approve = async () => {
    if (!sequence) return;
    setBusy('approve');
    try {
      for (const step of sequence.steps) {
        const edited = edits[step.id];
        if (edited === undefined || edited === step.body) continue;
        const saved = await apiFetch(`/followups/steps/${step.id}`, { method: 'PATCH', body: JSON.stringify({ body: edited }) });
        if (!saved.ok) return fail(saved, 'Could not save the edit');
      }
      const res = await apiFetch(`/leads/${agency.id}/followups/approve`, { method: 'POST' });
      if (!res.ok) return fail(res, 'Could not approve');
      setSequence(await res.json());
      setEdits({});
      onChanged();
      toast.success('Follow-ups approved');
    } catch {
      toast.error('Could not reach the backend.');
    } finally {
      setBusy(null);
    }
  };

  const stop = async () => {
    setBusy('stop');
    try {
      const res = await apiFetch(`/leads/${agency.id}/followups/stop`, { method: 'POST' });
      if (!res.ok) return fail(res, 'Could not stop');
      setSequence(await res.json());
      onChanged();
      toast.success('Follow-ups stopped');
    } catch {
      toast.error('Could not reach the backend.');
    } finally {
      setBusy(null);
    }
  };

  const open = sequence?.status === 'draft' || sequence?.status === 'active';
  const draft = sequence?.status === 'draft';
  const stepDate = (step: FollowUpStep): string => {
    if (step.status === 'sent' && step.sent_at) return `sent ${formatFollowUpDay(step.sent_at)}`;
    if (step.due_at) return formatFollowUpDay(step.due_at);
    return `day ${STEP_DAYS[step.step_no] ?? step.step_no} after the first email is sent`;
  };

  if (busy === 'load') return null;

  return (
    <section aria-label="Follow-ups" className="rounded border border-line bg-canvas p-3 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="inline-flex items-center gap-2 text-sm font-medium text-fg">
          <CalendarClock size={14} className="text-fg-muted" />
          Follow-ups
        </h4>
        {sequence && !open && (
          <span className="text-xs text-fg-subtle">
            {sequence.status === 'replied' ? 'Replied: sequence stopped' : `Sequence ${sequence.status}`}
            {sequence.stop_reason && sequence.status === 'stopped' ? ` (${sequence.stop_reason.replace('_', ' ')})` : ''}
          </span>
        )}
      </div>

      {(!sequence || !open) && (
        <button onClick={generate} disabled={busy !== null} className={buttonClass}>
          {busy === 'generate' ? <Loader2 size={14} className="animate-spin" /> : <MailPlus size={14} />}
          Add follow-ups
        </button>
      )}

      {open && sequence && (
        <>
          <p className="text-xs text-fg-subtle">
            {draft
              ? 'Nothing is sent until you approve the series. Edit the messages first; each keeps its opt-out line.'
              : 'Approved. Messages go out Mon–Fri 9–16 (Finnish time) while the backend is running, and stop if the lead replies or is marked do not contact.'}
          </p>
          {!sequence.send_enabled && (
            <p role="status" className="text-xs text-warning">
              Automatic sending is off on this backend (FOLLOWUPS_SEND_ENABLED), so approved messages will wait.
            </p>
          )}
          {sequence.steps.map((step) => (
            <div key={step.id} className="space-y-1.5">
              <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
                <span className="font-medium text-fg">
                  {step.step_no === 2 ? 'Last message' : 'Follow-up'} · {stepDate(step)}
                </span>
                <span className="text-fg-subtle">{step.subject}</span>
              </div>
              <textarea
                aria-label={`Follow-up ${step.step_no} body`}
                value={edits[step.id] ?? step.body}
                onChange={(e) => setEdits({ ...edits, [step.id]: e.target.value })}
                readOnly={!draft || step.status !== 'scheduled'}
                rows={9}
                className="w-full text-sm bg-surface border border-line-strong rounded px-3 py-2.5 text-fg resize-y leading-relaxed read-only:text-fg-muted"
              />
              {step.last_error && <p className="text-xs text-danger">{step.last_error}</p>}
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            {draft && (
              <>
                <button
                  onClick={approve}
                  disabled={busy !== null}
                  className="inline-flex items-center justify-center gap-2 h-control px-4 text-sm font-medium text-accent-fg bg-accent hover:bg-accent-hover disabled:opacity-40 rounded transition-colors"
                >
                  {busy === 'approve' ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                  Approve series
                </button>
                <button onClick={generate} disabled={busy !== null} className={buttonClass}>
                  {busy === 'generate' ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                  Regenerate
                </button>
              </>
            )}
            <button onClick={stop} disabled={busy !== null} className={buttonClass}>
              {busy === 'stop' ? <Loader2 size={14} className="animate-spin" /> : <OctagonX size={14} />}
              {draft ? 'Discard' : 'Stop series'}
            </button>
          </div>
        </>
      )}
    </section>
  );
};

export default FollowUpsPanel;
