import React, { useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, LayoutTemplate, Loader2, ExternalLink, RefreshCw, Trash2, Save, Plus, Minus } from 'lucide-react';
import { toast } from 'sonner';
import type { Demo, DemoContent, DemoPhoto, DemoTemplateOption, SavedAgency } from '../types/agency';
import { apiFetch } from '../lib/api';

interface DemoModalProps {
  isOpen: boolean;
  onClose: () => void;
  agency: SavedAgency;
}

const MIN_SERVICES = 3;
const MAX_SERVICES = 6;
const MAX_IMAGE_OPTIONS = 5;
// Sama utm_source kuin backendin UNSPLASH_APP_NAME (Unsplashin attribuutiovaatimus)
const UNSPLASH_UTM = 'utm_source=agency_hunter&utm_medium=referral';

const withUtm = (url: string): string => `${url}${url.includes('?') ? '&' : '?'}${UNSPLASH_UTM}`;
const thumbUrl = (photo: DemoPhoto): string =>
  `${photo.raw_url}${photo.raw_url.includes('?') ? '&' : '?'}w=320&h=200&fit=crop&auto=format&q=60`;

const inputClass =
  'w-full text-sm border-2 border-slate-200 rounded-lg px-3 py-2 text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 transition-colors';

const errorMessage = (status: number): string => {
  if (status === 428) return 'Add your sender profile in Settings (sidebar) before generating a demo.';
  if (status === 409) return 'This lead is marked do not contact.';
  if (status === 502) return 'The AI content did not pass validation twice. Try generating again.';
  return `Server error: ${status}`;
};

const toEditable = (demo: Demo): DemoContent => ({
  hero_title: demo.content.hero_title,
  hero_subtitle: demo.content.hero_subtitle,
  about: demo.content.about,
  services: demo.content.services.map((s) => ({ ...s })),
  price_note: demo.content.price_note,
});

const DemoModal: React.FC<DemoModalProps> = ({ isOpen, onClose, agency }) => {
  const [demo, setDemo] = useState<Demo | null>(null);
  const [templates, setTemplates] = useState<DemoTemplateOption[]>([]);
  const [draft, setDraft] = useState<DemoContent | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState('');
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<'generate' | 'save' | 'delete' | null>(null);
  const [error, setError] = useState('');
  const [previewVersion, setPreviewVersion] = useState(0);

  const applyDemo = (next: Demo) => {
    setDemo(next);
    setDraft(toEditable(next));
    setPreviewVersion((v) => v + 1);
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [tplRes, demoRes] = await Promise.all([
        apiFetch('/demo-templates'),
        apiFetch(`/leads/${agency.id}/demo`),
      ]);
      if (tplRes.ok) setTemplates(await tplRes.json());
      if (demoRes.status === 404) {
        setDemo(null);
        setDraft(null);
      } else if (demoRes.ok) {
        const data: Demo = await demoRes.json();
        setDemo(data);
        setDraft(toEditable(data));
      } else {
        setError(errorMessage(demoRes.status));
      }
    } catch {
      setError('Failed to load demo. Is the backend running?');
    } finally {
      setLoading(false);
    }
  }, [agency.id]);

  useEffect(() => {
    if (isOpen) load();
  }, [isOpen, load]);

  const generate = async () => {
    if (demo && !window.confirm('Generate new texts with AI? Your manual edits will be replaced.')) return;
    setBusy('generate');
    setError('');
    try {
      const res = await apiFetch(`/leads/${agency.id}/demo`, {
        method: 'POST',
        body: JSON.stringify(selectedTemplate ? { template: selectedTemplate } : {}),
      });
      if (!res.ok) {
        setError(errorMessage(res.status));
        return;
      }
      applyDemo(await res.json());
      toast.success('Demo generated');
    } catch {
      setError('Failed to generate demo. Is the backend running?');
    } finally {
      setBusy(null);
    }
  };

  const patch = async (body: Record<string, unknown>, successMessage?: string) => {
    setBusy('save');
    try {
      const res = await apiFetch(`/leads/${agency.id}/demo`, { method: 'PATCH', body: JSON.stringify(body) });
      if (!res.ok) {
        toast.error(res.status === 422 ? 'Check the texts: 3–6 services and no empty fields' : errorMessage(res.status));
        return;
      }
      applyDemo(await res.json());
      if (successMessage) toast.success(successMessage);
    } catch {
      toast.error('Failed to update demo');
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    if (!window.confirm('Delete this demo? The preview link stops working.')) return;
    setBusy('delete');
    try {
      const res = await apiFetch(`/leads/${agency.id}/demo`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`${res.status}`);
      setDemo(null);
      setDraft(null);
      toast.success('Demo deleted');
    } catch {
      toast.error('Failed to delete demo');
    } finally {
      setBusy(null);
    }
  };

  const updateService = (index: number, key: 'name' | 'description', value: string) =>
    setDraft((d) =>
      d ? { ...d, services: d.services.map((s, i) => (i === index ? { ...s, [key]: value } : s)) } : d,
    );

  const currentTemplate = templates.find((t) => t.id === demo?.template);

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
            className="relative w-full max-w-6xl max-h-[92vh] bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden flex flex-col"
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 bg-gradient-to-r from-sky-50 to-indigo-50">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-sky-100 rounded-lg">
                  <LayoutTemplate size={18} className="text-sky-700" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-slate-900">Demo website</h3>
                  <p className="text-xs text-slate-500">
                    {agency.name}
                    {demo ? ` · ${demo.status}` : ''}
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

            <div className="flex-1 overflow-y-auto">
              {loading ? (
                <div className="flex items-center justify-center py-24">
                  <Loader2 size={28} className="animate-spin text-slate-400" />
                </div>
              ) : !demo ? (
                <div className="px-6 py-10 max-w-lg mx-auto text-center space-y-4">
                  <p className="text-sm text-slate-600">
                    Generate a one-page draft website for this lead. The AI writes only the texts; the page is built
                    from a ready-made template and is clearly marked as a draft (noindex).
                  </p>
                  {templates.length > 0 && (
                    <select
                      value={selectedTemplate}
                      onChange={(e) => setSelectedTemplate(e.target.value)}
                      className={inputClass}
                      aria-label="Template"
                    >
                      <option value="">Template: automatic (by business type)</option>
                      {templates.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                  )}
                  {error && <p className="text-sm text-red-600">{error}</p>}
                  <button
                    onClick={generate}
                    disabled={busy !== null}
                    className="inline-flex items-center gap-2 px-6 py-2.5 text-sm font-semibold text-white bg-sky-600 hover:bg-sky-700 rounded-lg transition-colors disabled:opacity-60"
                  >
                    {busy === 'generate' ? <Loader2 size={16} className="animate-spin" /> : <LayoutTemplate size={16} />}
                    {busy === 'generate' ? 'Generating...' : 'Generate demo'}
                  </button>
                </div>
              ) : (
                <div className="grid lg:grid-cols-[1fr_340px]">
                  <div className="p-4 bg-slate-100 border-b lg:border-b-0 lg:border-r border-slate-200">
                    <iframe
                      key={previewVersion}
                      title={`Demo preview: ${agency.name}`}
                      src={`${demo.preview_url}?v=${previewVersion}`}
                      sandbox=""
                      className="w-full h-[60vh] lg:h-[70vh] bg-white rounded-lg border border-slate-200"
                    />
                  </div>

                  <div className="p-5 space-y-4">
                    {error && <p className="text-sm text-red-600">{error}</p>}
                    <div className="grid grid-cols-2 gap-2">
                      <select
                        value={demo.template}
                        onChange={(e) => patch({ template: e.target.value })}
                        disabled={busy !== null}
                        className={inputClass}
                        aria-label="Template"
                      >
                        {templates.map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.label}
                          </option>
                        ))}
                      </select>
                      <select
                        value={demo.color_scheme}
                        onChange={(e) => patch({ color_scheme: e.target.value })}
                        disabled={busy !== null}
                        className={inputClass}
                        aria-label="Colors"
                      >
                        {(currentTemplate?.color_schemes ?? []).map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.label}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <span className="block text-xs font-semibold text-slate-700 uppercase tracking-wide mb-1.5">
                        Hero image
                      </span>
                      {demo.content.images.options.length === 0 ? (
                        <p className="text-xs text-slate-500">
                          No photos available (gradient is used). Set UNSPLASH_ACCESS_KEY in backend .env and regenerate.
                        </p>
                      ) : (
                        <div className="grid grid-cols-3 gap-2">
                          {demo.content.images.options.slice(0, MAX_IMAGE_OPTIONS).map((photo) => {
                            const selected = demo.content.images.hero?.id === photo.id;
                            return (
                              <figure key={photo.id} className="m-0">
                                <button
                                  type="button"
                                  onClick={() => !selected && patch({ hero_image_id: photo.id })}
                                  disabled={busy !== null}
                                  aria-pressed={selected}
                                  aria-label={`Use photo by ${photo.photographer_name}`}
                                  className={`block w-full overflow-hidden rounded-lg border-2 transition-colors ${
                                    selected ? 'border-sky-600 ring-2 ring-sky-200' : 'border-transparent hover:border-slate-300'
                                  }`}
                                >
                                  <img src={thumbUrl(photo)} alt={photo.alt} className="w-full h-16 object-cover" loading="lazy" />
                                </button>
                                <figcaption className="mt-0.5 text-[10px] leading-tight text-slate-400 truncate">
                                  <a href={withUtm(photo.photographer_url)} target="_blank" rel="noopener noreferrer" className="hover:underline">
                                    {photo.photographer_name}
                                  </a>{' '}
                                  /{' '}
                                  <a href={withUtm('https://unsplash.com/')} target="_blank" rel="noopener noreferrer" className="hover:underline">
                                    Unsplash
                                  </a>
                                </figcaption>
                              </figure>
                            );
                          })}
                          <button
                            type="button"
                            onClick={() => demo.content.images.hero && patch({ hero_image_id: 'none' })}
                            disabled={busy !== null}
                            aria-pressed={!demo.content.images.hero}
                            className={`h-16 rounded-lg border-2 text-[11px] font-medium text-slate-600 bg-gradient-to-br from-slate-100 to-slate-200 ${
                              !demo.content.images.hero ? 'border-sky-600 ring-2 ring-sky-200' : 'border-transparent hover:border-slate-300'
                            }`}
                          >
                            No photo
                          </button>
                        </div>
                      )}
                    </div>

                    {draft && (
                      <div className="space-y-3">
                        <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide">
                          Headline
                          <input
                            value={draft.hero_title}
                            onChange={(e) => setDraft({ ...draft, hero_title: e.target.value })}
                            maxLength={80}
                            className={`${inputClass} mt-1 normal-case font-normal tracking-normal`}
                          />
                        </label>
                        <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide">
                          Subheadline
                          <input
                            value={draft.hero_subtitle}
                            onChange={(e) => setDraft({ ...draft, hero_subtitle: e.target.value })}
                            maxLength={180}
                            className={`${inputClass} mt-1 normal-case font-normal tracking-normal`}
                          />
                        </label>
                        <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide">
                          About
                          <textarea
                            value={draft.about}
                            onChange={(e) => setDraft({ ...draft, about: e.target.value })}
                            maxLength={700}
                            rows={4}
                            className={`${inputClass} mt-1 normal-case font-normal tracking-normal resize-y`}
                          />
                        </label>

                        <div>
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-xs font-semibold text-slate-700 uppercase tracking-wide">
                              Services ({draft.services.length})
                            </span>
                            <div className="flex gap-1">
                              <button
                                type="button"
                                aria-label="Remove last service"
                                disabled={draft.services.length <= MIN_SERVICES}
                                onClick={() => setDraft({ ...draft, services: draft.services.slice(0, -1) })}
                                className="p-1 rounded text-slate-500 hover:bg-slate-100 disabled:opacity-30"
                              >
                                <Minus size={14} />
                              </button>
                              <button
                                type="button"
                                aria-label="Add service"
                                disabled={draft.services.length >= MAX_SERVICES}
                                onClick={() =>
                                  setDraft({ ...draft, services: [...draft.services, { name: '', description: '' }] })
                                }
                                className="p-1 rounded text-slate-500 hover:bg-slate-100 disabled:opacity-30"
                              >
                                <Plus size={14} />
                              </button>
                            </div>
                          </div>
                          <div className="space-y-2">
                            {draft.services.map((s, i) => (
                              <div key={i} className="space-y-1 p-2 rounded-lg bg-slate-50">
                                <input
                                  value={s.name}
                                  onChange={(e) => updateService(i, 'name', e.target.value)}
                                  maxLength={60}
                                  placeholder="Service name"
                                  aria-label={`Service ${i + 1} name`}
                                  className={inputClass}
                                />
                                <input
                                  value={s.description}
                                  onChange={(e) => updateService(i, 'description', e.target.value)}
                                  maxLength={220}
                                  placeholder="Description"
                                  aria-label={`Service ${i + 1} description`}
                                  className={inputClass}
                                />
                              </div>
                            ))}
                          </div>
                        </div>

                        <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide">
                          Prices note
                          <input
                            value={draft.price_note}
                            onChange={(e) => setDraft({ ...draft, price_note: e.target.value })}
                            maxLength={120}
                            className={`${inputClass} mt-1 normal-case font-normal tracking-normal`}
                          />
                        </label>

                        <button
                          onClick={() => patch({ content: draft }, 'Texts saved')}
                          disabled={busy !== null}
                          className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg transition-colors disabled:opacity-60"
                        >
                          {busy === 'save' ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                          Save texts
                        </button>
                      </div>
                    )}

                    <div className="pt-2 border-t border-slate-200 flex flex-wrap gap-2">
                      <a
                        href={demo.preview_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-sky-700 bg-sky-50 hover:bg-sky-100 rounded-lg transition-colors"
                      >
                        <ExternalLink size={13} />
                        Open in new tab
                      </a>
                      <button
                        onClick={generate}
                        disabled={busy !== null}
                        className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors disabled:opacity-60"
                      >
                        {busy === 'generate' ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                        Regenerate
                      </button>
                      <button
                        onClick={remove}
                        disabled={busy !== null}
                        className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-rose-700 bg-rose-50 hover:bg-rose-100 rounded-lg transition-colors disabled:opacity-60"
                      >
                        <Trash2 size={13} />
                        Delete
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};

export default DemoModal;
