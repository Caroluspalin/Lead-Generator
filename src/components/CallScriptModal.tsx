import React, { useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Copy, RefreshCw, PhoneCall, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import type { SavedAgency } from '../types/agency';
import { apiFetch } from '../lib/api';

interface CallScriptModalProps {
  isOpen: boolean;
  onClose: () => void;
  agency: SavedAgency;
}

interface CallScript {
  script: string;
  model: string;
}

const CallScriptModal: React.FC<CallScriptModalProps> = ({ isOpen, onClose, agency }) => {
  const [result, setResult] = useState<CallScript | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const fetchScript = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch(`/leads/${agency.id}/generate-call-script`, { method: 'POST' });
      if (res.status === 409) {
        setError('This lead is marked do not contact.');
        return;
      }
      if (res.status === 428) {
        setError('Add your sender profile in Settings (sidebar) before generating drafts and call scripts.');
        return;
      }
      if (!res.ok) {
        throw new Error(`Server error: ${res.status}`);
      }
      const data: CallScript = await res.json();
      setResult(data);
    } catch (err) {
      console.error(err);
      setError('Failed to generate call script. Is the backend running?');
    } finally {
      setLoading(false);
    }
  }, [agency.id]);

  useEffect(() => {
    if (isOpen) {
      setResult(null);
      fetchScript();
    }
  }, [isOpen, fetchScript]);

  const handleCopy = async () => {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.script);
      toast.success('Copied to clipboard!');
    } catch {
      toast.error('Failed to copy');
    }
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 bg-backdrop/70"
            onClick={onClose}
          />

          <motion.div
            role="dialog"
            aria-modal="true"
            aria-labelledby="call-script-title"
            initial={{ opacity: 0, scale: 0.98, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.98, y: 8 }}
            transition={{ duration: 0.2 }}
            className="relative w-full max-w-xl bg-surface rounded-lg border border-line-strong shadow-overlay overflow-hidden"
          >
            <div className="flex items-center justify-between gap-3 px-5 py-3.5 border-b border-line">
              <div className="flex items-center gap-2.5 min-w-0">
                <PhoneCall size={16} className="shrink-0 text-fg-muted" />
                <div className="min-w-0">
                  <h3 id="call-script-title" className="text-base font-semibold text-fg">Call script (~30 s)</h3>
                  <p className="text-xs text-fg-subtle truncate">
                    {agency.name}
                    {agency.phone ? ` · ${agency.phone}` : ''}
                  </p>
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

            <div className="px-5 py-4 max-h-[60vh] overflow-y-auto">
              {loading ? (
                <div role="status" className="flex flex-col items-center justify-center py-16 gap-3">
                  <Loader2 size={20} className="text-fg-subtle animate-spin" />
                  <p className="text-sm text-fg-muted">AI is writing...</p>
                </div>
              ) : error ? (
                <div className="py-8 text-center">
                  <p role="alert" className="text-sm text-danger mb-3">{error}</p>
                  <button
                    onClick={() => fetchScript()}
                    className="inline-flex items-center gap-2 h-control px-3 text-sm font-medium text-fg border border-line-strong hover:bg-raised rounded transition-colors"
                  >
                    <RefreshCw size={14} />
                    Try again
                  </button>
                </div>
              ) : result ? (
                <>
                  <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-fg bg-canvas border border-line rounded px-3.5 py-3">
                    {result.script}
                  </pre>
                  <p className="text-2xs text-fg-subtle text-right mt-2">Model: {result.model}</p>
                </>
              ) : null}
            </div>

            {!loading && result && (
              <div className="px-5 py-3 border-t border-line flex justify-end gap-2">
                <button
                  onClick={() => fetchScript()}
                  className="inline-flex items-center gap-2 h-control px-3 text-sm font-medium text-fg border border-line-strong hover:bg-raised rounded transition-colors"
                >
                  <RefreshCw size={14} />
                  Regenerate
                </button>
                <button
                  onClick={handleCopy}
                  className="inline-flex items-center justify-center gap-2 h-control px-4 text-sm font-medium text-accent-fg bg-accent hover:bg-accent-hover rounded transition-colors"
                >
                  <Copy size={14} />
                  Copy
                </button>
              </div>
            )}
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};

export default CallScriptModal;
