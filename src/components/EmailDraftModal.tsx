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

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={onClose}
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ duration: 0.2 }}
            className="relative w-full max-w-2xl max-h-[94vh] flex flex-col bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 bg-gradient-to-r from-indigo-50 to-purple-50 shrink-0">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-indigo-100 rounded-lg">
                  <Sparkles size={18} className="text-indigo-600" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-slate-900">
                    AI Email Draft
                  </h3>
                  <p className="text-xs text-slate-500">{agency.name}</p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            {/* Body */}
            <div className="px-6 py-5 space-y-4 flex-1 min-h-0 overflow-y-auto">
              {loading ? (
                <div className="flex flex-col items-center justify-center py-16 gap-4">
                  <div className="relative">
                    <Sparkles
                      size={32}
                      className="text-indigo-500 animate-pulse"
                    />
                  </div>
                  <p className="text-sm font-medium text-indigo-600 animate-pulse">
                    {loadingPhase === 'scan'
                      ? 'Analyzing website for personalization...'
                      : 'AI is writing...'}
                  </p>
                </div>
              ) : error ? (
                <div className="py-8 text-center">
                  <p className="text-sm text-red-600 mb-3">{error}</p>
                  <button
                    onClick={() => fetchDraft()}
                    className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-red-700 bg-red-50 hover:bg-red-100 rounded-lg transition-colors"
                  >
                    <RefreshCw size={14} />
                    Try again
                  </button>
                </div>
              ) : draft ? (
                <>
                  {/* Subject */}
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide mb-1.5">
                      Subject
                    </label>
                    <input
                      type="text"
                      value={draft.subject}
                      onChange={(e) =>
                        setDraft({ ...draft, subject: e.target.value })
                      }
                      className="w-full text-sm border-2 border-slate-200 rounded-lg px-4 py-2.5 text-slate-800 font-medium focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 transition-colors"
                    />
                  </div>

                  {/* Body */}
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide mb-1.5">
                      Email Body
                    </label>
                    <textarea
                      ref={textareaRef}
                      value={draft.body}
                      onChange={(e) =>
                        setDraft({ ...draft, body: e.target.value })
                      }
                      rows={10}
                      className="w-full text-sm border-2 border-slate-200 rounded-lg px-4 py-3 text-slate-700 resize-y focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 transition-colors leading-relaxed"
                    />
                  </div>

                  <p className="text-xs text-slate-400 text-right">
                    Model: {draft.model}
                  </p>
                </>
              ) : null}
            </div>

            {/* Footer — Iterate & Actions */}
            {!loading && draft && (
              <div className="px-6 py-4 border-t border-slate-200 bg-slate-50 space-y-3 shrink-0">
                {/* Instruction + Regenerate */}
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={instruction}
                    onChange={(e) => setInstruction(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleRegenerate();
                    }}
                    placeholder="E.g. make it shorter or more casual..."
                    className="flex-1 text-sm border-2 border-slate-200 rounded-lg px-4 py-2.5 text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 transition-colors"
                  />
                  <button
                    onClick={handleRegenerate}
                    className="inline-flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-indigo-700 bg-indigo-100 hover:bg-indigo-200 rounded-lg transition-colors whitespace-nowrap"
                  >
                    <RefreshCw size={14} />
                    Regenerate
                  </button>
                </div>

                {/* Copy & Send */}
                <div className="flex gap-2">
                  <button
                    onClick={handleCopy}
                    className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg transition-colors shadow-sm shadow-indigo-200"
                  >
                    <Copy size={14} />
                    Copy
                  </button>
                  <button
                    onClick={handleSend}
                    disabled={sending || !recipientEmail}
                    className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-semibold text-white bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors shadow-sm shadow-emerald-200"
                  >
                    {sending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                    Send
                  </button>
                </div>

                {publicDemoUrl && !draft.body.includes(publicDemoUrl) && (
                  <button
                    onClick={addDemoLink}
                    disabled={addingLink}
                    className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-sky-700 bg-sky-50 hover:bg-sky-100 border border-sky-200 rounded-lg transition-colors disabled:opacity-60"
                  >
                    {addingLink ? <Loader2 size={14} className="animate-spin" /> : <Link2 size={14} />}
                    Add demo link to this draft
                  </button>
                )}

                {/* Piilotetaan kun vastaanottaja on kirjoitettu käsin */}
                {!agency.email && !recipientEmail.trim() && (
                  <div role="status" className="flex flex-wrap items-center gap-2 p-3 rounded-lg bg-amber-50 border border-amber-200 text-sm text-amber-900">
                    <AlertTriangle size={16} className="shrink-0" />
                    <span className="flex-1 min-w-[12rem]">
                      No email address found for this lead. Enter it below, use Find email on the card, or call instead.
                    </span>
                    {onOpenCallScript && (
                      <button
                        onClick={onOpenCallScript}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-emerald-800 bg-emerald-100 hover:bg-emerald-200 rounded-lg transition-colors"
                      >
                        <PhoneCall size={13} />
                        Call script
                      </button>
                    )}
                  </div>
                )}

                {/* Recipient */}
                <input
                  type="email"
                  value={recipientEmail}
                  onChange={(e) => setRecipientEmail(e.target.value)}
                  placeholder="Recipient email (e.g. info@yritys.fi)"
                  className="w-full text-sm border-2 border-slate-200 rounded-lg px-4 py-2.5 text-slate-700 focus:outline-none focus:ring-2 focus:ring-emerald-100 focus:border-emerald-500 transition-colors"
                />
              </div>
            )}
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};

export default EmailDraftModal;
