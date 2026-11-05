import React, { useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Copy, RefreshCw, PhoneCall } from 'lucide-react';
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
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={onClose}
          />

          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ duration: 0.2 }}
            className="relative w-full max-w-xl bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden"
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 bg-gradient-to-r from-emerald-50 to-teal-50">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-emerald-100 rounded-lg">
                  <PhoneCall size={18} className="text-emerald-700" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-slate-900">Call Script (~30 s)</h3>
                  <p className="text-xs text-slate-500">
                    {agency.name}
                    {agency.phone ? ` · ${agency.phone}` : ''}
                  </p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            <div className="px-6 py-5 max-h-[60vh] overflow-y-auto">
              {loading ? (
                <div className="flex flex-col items-center justify-center py-16 gap-4">
                  <PhoneCall size={32} className="text-emerald-500 animate-pulse" />
                  <p className="text-sm font-medium text-emerald-700 animate-pulse">AI is writing...</p>
                </div>
              ) : error ? (
                <div className="py-8 text-center">
                  <p className="text-sm text-red-600 mb-3">{error}</p>
                  <button
                    onClick={() => fetchScript()}
                    className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-red-700 bg-red-50 hover:bg-red-100 rounded-lg transition-colors"
                  >
                    <RefreshCw size={14} />
                    Try again
                  </button>
                </div>
              ) : result ? (
                <>
                  <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-slate-700 bg-slate-50 border-2 border-slate-200 rounded-lg px-4 py-3">
                    {result.script}
                  </pre>
                  <p className="text-xs text-slate-400 text-right mt-2">Model: {result.model}</p>
                </>
              ) : null}
            </div>

            {!loading && result && (
              <div className="px-6 py-4 border-t border-slate-200 bg-slate-50 flex gap-2">
                <button
                  onClick={() => fetchScript()}
                  className="inline-flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-emerald-700 bg-emerald-100 hover:bg-emerald-200 rounded-lg transition-colors"
                >
                  <RefreshCw size={14} />
                  Regenerate
                </button>
                <button
                  onClick={handleCopy}
                  className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-semibold text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg transition-colors shadow-sm shadow-emerald-200"
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
