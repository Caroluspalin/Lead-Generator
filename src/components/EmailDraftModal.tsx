import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Copy, RefreshCw, Sparkles, Send, Loader2, AlertTriangle, PhoneCall, Link2 } from 'lucide-react';
import { toast } from 'sonner';
import type { Demo, SavedAgency } from '../types/agency';
import { apiFetch } from '../lib/api';
import { outreachErrorMessage, readDetail } from '../lib/apiErrors';

interface EmailDraftModalProps {
  isOpen: boolean;
  onClose: () => void;
  agency: SavedAgency;
  // "Publish & create email" -ketju: backend palauttaa 409 jos demoa ei ole julkaistu
  requireDemoLink?: boolean;
  onOpenCallScript?: () => void;
}

interface EmailDraft {
  subject: string;
  body: string;
  model: string;
}

const EmailDraftModal: React.FC<EmailDraftModalProps> = ({
  isOpen,
  onClose,
  agency,
  requireDemoLink = false,
  onOpenCallScript,
}) => {
  const [publicDemoUrl, setPublicDemoUrl] = useState<string | null>(null);
  const [addingLink, setAddingLink] = useState(false);
  const [draft, setDraft] = useState<EmailDraft | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingPhase, setLoadingPhase] = useState<'scan' | 'generate'>('generate');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [instruction, setInstruction] = useState('');
  const [recipientEmail, setRecipientEmail] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const fetchDraft = useCallback(async (extraInstruction?: string) => {
    setLoading(true);
    setLoadingPhase(agency.website ? 'scan' : 'generate');
    setError('');

    // Vaihda viesti generointi-vaiheeseen 3s jälkeen (scraping valmis)
    const phaseTimer = agency.website
      ? setTimeout(() => setLoadingPhase('generate'), 3000)
      : undefined;

    try {
      const res = await apiFetch(
        `/leads/${agency.id}/generate-email`,
        {
          method: 'POST',
          body: JSON.stringify({
            instruction: extraInstruction || undefined,
            require_demo_link: requireDemoLink || undefined,
          }),
        },
      );
      if (res.status === 409 || res.status === 428) {
        setError(outreachErrorMessage(res.status, await readDetail(res)));
        return;
      }
      if (!res.ok) {
        throw new Error(`Server error: ${res.status}`);
      }
      const data: EmailDraft = await res.json();
      setDraft(data);
    } catch (err) {
      console.error(err);
      setError('Failed to generate email. Is the backend running?');
    } finally {
      if (phaseTimer) clearTimeout(phaseTimer);
      setLoading(false);
    }
  }, [agency.id, agency.website, requireDemoLink]);

  // Julkaistun demon osoite: "Add demo link" jo kirjoitettuun luonnokseen ilman uutta AI-kutsua
  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    apiFetch(`/leads/${agency.id}/demo`)
      .then(async (res) => {
        if (cancelled) return;
        if (!res.ok) {
          setPublicDemoUrl(null);
          return;
        }
        const demo: Demo = await res.json();
        if (!cancelled) setPublicDemoUrl(demo.status === 'published' ? demo.public_url : null);
      })
      .catch(() => {
        if (!cancelled) setPublicDemoUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, agency.id]);

  const addDemoLink = async () => {
    if (!draft) return;
    setAddingLink(true);
    try {
      const res = await apiFetch(`/leads/${agency.id}/email/demo-link`, {
        method: 'POST',
        body: JSON.stringify({ body: draft.body }),
      });
      if (!res.ok) {
        toast.error(outreachErrorMessage(res.status, await readDetail(res)));
        return;
      }
      const data: { body: string } = await res.json();
      setDraft({ ...draft, body: data.body });
      toast.success('Demo link added');
    } catch {
      toast.error('Failed to add the demo link');
    } finally {
      setAddingLink(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      setDraft(null);
      setInstruction('');
      setError('');
      fetchDraft();
    }
  }, [isOpen, fetchDraft]);

  // Erillinen efekti: taustalla löytyvä osoite esitäyttää kentän ilman uutta AI-generointia
  useEffect(() => {
    if (isOpen) {
      setRecipientEmail(agency.email ?? '');
    }
  }, [isOpen, agency.email]);

  const handleRegenerate = () => {
    fetchDraft(instruction);
  };

  const handleCopy = async () => {
    if (!draft) return;
    const text = `Subject: ${draft.subject}\n\n${draft.body}`;
    try {
      await navigator.clipboard.writeText(text);
      toast.success('Copied to clipboard!');
    } catch {
      toast.error('Failed to copy');
    }
  };

  const handleSend = async () => {
    if (!draft || !recipientEmail) {
      toast.error('Enter a recipient email address');
      return;
    }
    setSending(true);
    try {
      const res = await apiFetch('/send-email', {
        method: 'POST',
        body: JSON.stringify({
          to: recipientEmail,
          subject: draft.subject,
          body: draft.body,
          lead_id: agency.id,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(data.detail || `${res.status}`);
      }
      toast.success(`Email sent to ${recipientEmail}`);
      setRecipientEmail('');
    } catch (err) {
      toast.error(`Failed to send: ${(err as Error).message}`);
    } finally {
      setSending(false);
    }
  };

  const fieldClass =
    'w-full text-sm bg-canvas border border-line-strong rounded px-3 text-fg transition-colors';
  const labelClass = 'block text-2xs font-medium text-fg-muted mb-1.5';
  const secondaryButton =
    'inline-flex items-center justify-center gap-2 h-control px-3 text-sm font-medium text-fg border border-line-strong hover:bg-raised rounded transition-colors whitespace-nowrap disabled:opacity-60';

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 bg-backdrop/70"
            onClick={onClose}
          />

          {/* Modal */}
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-labelledby="email-draft-title"
            initial={{ opacity: 0, scale: 0.98, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.98, y: 8 }}
            transition={{ duration: 0.2 }}
            className="relative w-full max-w-2xl max-h-[94vh] flex flex-col bg-surface rounded-lg border border-line-strong shadow-overlay overflow-hidden"
          >
            {/* Header */}
            <div className="flex items-center justify-between gap-3 px-5 py-3.5 border-b border-line shrink-0">
              <div className="flex items-center gap-2.5 min-w-0">
                <Sparkles size={16} className="shrink-0 text-fg-muted" />
                <div className="min-w-0">
                  <h3 id="email-draft-title" className="text-base font-semibold text-fg">
                    AI email draft
                  </h3>
                  <p className="text-xs text-fg-subtle truncate">{agency.name}</p>
                </div>
              </div>
              <button
                onClick={onClose}
                aria-label="Close"
                className="grid size-control-sm shrink-0 place-content-center rounded text-fg-subtle hover:text-fg hover:bg-raised transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            {/* Body */}
            <div className="px-5 py-4 space-y-3.5 flex-1 min-h-0 overflow-y-auto">
              {loading ? (
                <div role="status" className="flex flex-col items-center justify-center py-16 gap-3">
                  <Loader2 size={20} className="text-fg-subtle animate-spin" />
                  <p className="text-sm text-fg-muted">
                    {loadingPhase === 'scan'
                      ? 'Analyzing website for personalization...'
                      : 'AI is writing...'}
                  </p>
                </div>
              ) : error ? (
                <div className="py-8 text-center">
                  <p role="alert" className="text-sm text-danger mb-3">{error}</p>
                  <button
                    onClick={() => fetchDraft()}
                    className={secondaryButton}
                  >
                    <RefreshCw size={14} />
                    Try again
                  </button>
                </div>
              ) : draft ? (
                <>
                  {/* Subject */}
                  <div>
                    <label htmlFor="email-subject" className={labelClass}>
                      Subject
                    </label>
                    <input
                      id="email-subject"
                      type="text"
                      value={draft.subject}
                      onChange={(e) =>
                        setDraft({ ...draft, subject: e.target.value })
                      }
                      className={`${fieldClass} h-control font-medium`}
                    />
                  </div>

                  {/* Body */}
                  <div>
                    <label htmlFor="email-body" className={labelClass}>
                      Body
                    </label>
                    <textarea
                      id="email-body"
                      ref={textareaRef}
                      value={draft.body}
                      onChange={(e) =>
                        setDraft({ ...draft, body: e.target.value })
                      }
                      rows={10}
                      className={`${fieldClass} py-2.5 resize-y leading-relaxed`}
                    />
                  </div>

                  <p className="text-2xs text-fg-subtle text-right">
                    Model: {draft.model}
                  </p>
                </>
              ) : null}
            </div>

            {/* Footer — Iterate & Actions */}
            {!loading && draft && (
              <div className="px-5 py-3.5 border-t border-line bg-canvas space-y-2.5 shrink-0">
                {/* Instruction + Regenerate */}
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={instruction}
                    onChange={(e) => setInstruction(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleRegenerate();
                    }}
                    aria-label="Instruction for regenerating"
                    placeholder="E.g. make it shorter or more casual..."
                    className={`${fieldClass} h-control flex-1 bg-surface`}
                  />
                  <button
                    onClick={handleRegenerate}
                    className={secondaryButton}
                  >
                    <RefreshCw size={14} />
                    Regenerate
                  </button>
                </div>

                {publicDemoUrl && !draft.body.includes(publicDemoUrl) && (
                  <button
                    onClick={addDemoLink}
                    disabled={addingLink}
                    className={`${secondaryButton} w-full`}
                  >
                    {addingLink ? <Loader2 size={14} className="animate-spin" /> : <Link2 size={14} />}
                    Add demo link to this draft
                  </button>
                )}

                {/* Piilotetaan kun vastaanottaja on kirjoitettu käsin */}
                {!agency.email && !recipientEmail.trim() && (
                  <div role="status" className="flex flex-wrap items-center gap-2 px-3 py-2 rounded border border-warning/30 bg-warning/10 text-sm text-fg">
                    <AlertTriangle size={14} className="shrink-0 text-warning" />
                    <span className="flex-1 min-w-[12rem]">
                      No email address found for this lead. Enter it below, use Find email on the card, or call instead.
                    </span>
                    {onOpenCallScript && (
                      <button
                        onClick={onOpenCallScript}
                        className="inline-flex items-center gap-1.5 h-control-sm px-2.5 text-xs font-medium text-fg border border-line-strong hover:bg-raised rounded transition-colors"
                      >
                        <PhoneCall size={13} />
                        Call script
                      </button>
                    )}
                  </div>
                )}

                {/* Recipient + Copy & Send */}
                <div className="flex gap-2">
                  <input
                    type="email"
                    value={recipientEmail}
                    onChange={(e) => setRecipientEmail(e.target.value)}
                    aria-label="Recipient email"
                    placeholder="Recipient email (e.g. info@yritys.fi)"
                    className={`${fieldClass} h-control flex-1 bg-surface`}
                  />
                  <button
                    onClick={handleCopy}
                    className={secondaryButton}
                  >
                    <Copy size={14} />
                    Copy
                  </button>
                  <button
                    onClick={handleSend}
                    disabled={sending || !recipientEmail}
                    className="inline-flex items-center justify-center gap-2 h-control px-4 text-sm font-medium text-accent-fg bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed rounded transition-colors"
                  >
                    {sending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                    Send
                  </button>
                </div>
              </div>
            )}
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};

export default EmailDraftModal;
