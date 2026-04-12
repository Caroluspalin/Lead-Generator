import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Copy, RefreshCw, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import type { SavedAgency } from '../types/agency';

interface EmailDraftModalProps {
  isOpen: boolean;
  onClose: () => void;
  agency: SavedAgency;
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
}) => {
  const [draft, setDraft] = useState<EmailDraft | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [instruction, setInstruction] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const fetchDraft = async (extraInstruction?: string) => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(
        `http://127.0.0.1:8000/leads/${agency.id}/generate-email`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            instruction: extraInstruction || undefined,
          }),
        },
      );
      if (!res.ok) {
        throw new Error(`Server error: ${res.status}`);
      }
      const data: EmailDraft = await res.json();
      setDraft(data);
    } catch (err) {
      console.error(err);
      setError('Failed to generate email. Is the backend running?');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      setDraft(null);
      setInstruction('');
      setError('');
      fetchDraft();
    }
  }, [isOpen, agency.id]);

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
            className="relative w-full max-w-2xl bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 bg-gradient-to-r from-indigo-50 to-purple-50">
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
            <div className="px-6 py-5 space-y-4 max-h-[60vh] overflow-y-auto">
              {loading ? (
                <div className="flex flex-col items-center justify-center py-16 gap-4">
                  <div className="relative">
                    <Sparkles
                      size={32}
                      className="text-indigo-500 animate-pulse"
                    />
                  </div>
                  <p className="text-sm font-medium text-indigo-600 animate-pulse">
                    AI is writing...
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
              <div className="px-6 py-4 border-t border-slate-200 bg-slate-50 space-y-3">
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

                {/* Copy */}
                <button
                  onClick={handleCopy}
                  className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg transition-colors shadow-sm shadow-indigo-200"
                >
                  <Copy size={14} />
                  Copy to Clipboard
                </button>
              </div>
            )}
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};

export default EmailDraftModal;
