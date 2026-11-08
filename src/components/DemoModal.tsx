import React, { useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, LayoutTemplate, Loader2, ExternalLink, RefreshCw, Trash2, Save, Plus, Minus, Globe, Copy, EyeOff, Send, Smartphone } from 'lucide-react';
import { toast } from 'sonner';
import type { Demo, DemoContent, DemoPhoto, DemoTemplateOption, SavedAgency } from '../types/agency';
import { apiFetch } from '../lib/api';
import { outreachErrorMessage, readDetail } from '../lib/apiErrors';

interface DemoModalProps {
  isOpen: boolean;
  onClose: () => void;
  agency: SavedAgency;
  // Kutsutaan kun demo on julkaistu: avaa EmailDraftModalin (julkaistu linkki mukaan)
  onCreateEmail?: () => void;
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
  'w-full text-sm font-normal bg-canvas border border-line-strong rounded px-2.5 py-1.5 text-fg transition-colors';

// Puhelinnäkymän kuvakaappaus (backend /demo/screenshot, Playwright). unavailable = Playwright
// puuttuu palvelimelta (501): näytetään skaalattu 390 px iframe.
type PhoneShot =
  | { status: 'loading' }
  | { status: 'ready'; url: string }
  | { status: 'unavailable' }
  | { status: 'error' };

const toEditable = (demo: Demo): DemoContent => ({
  hero_title: demo.content.hero_title,
  hero_subtitle: demo.content.hero_subtitle,
  about_title: demo.content.about_title,
  about: demo.content.about,
  services: demo.content.services.map((s) => ({ ...s })),
  price_note: demo.content.price_note,
});

const DemoModal: React.FC<DemoModalProps> = ({ isOpen, onClose, agency, onCreateEmail }) => {
  const [demo, setDemo] = useState<Demo | null>(null);
  const [templates, setTemplates] = useState<DemoTemplateOption[]>([]);
  const [draft, setDraft] = useState<DemoContent | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState('');
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<'generate' | 'save' | 'delete' | 'publish' | null>(null);
  const [error, setError] = useState('');
  const [previewVersion, setPreviewVersion] = useState(0);
  const [phoneShot, setPhoneShot] = useState<PhoneShot>({ status: 'loading' });

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
        setError(outreachErrorMessage(demoRes.status, await readDetail(demoRes)));
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

  // Automaattinen 390 px kuvakaappaus aina kun demo muuttuu: tarkistus ennen julkaisua
  const demoId = demo?.id;
  useEffect(() => {
    if (!isOpen || demoId === undefined) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    setPhoneShot({ status: 'loading' });
    apiFetch(`/leads/${agency.id}/demo/screenshot`)
      .then(async (res) => {
        if (cancelled) return;
        if (res.status === 501) {
          setPhoneShot({ status: 'unavailable' });
          return;
        }
        if (!res.ok) {
          setPhoneShot({ status: 'error' });
          return;
        }
        objectUrl = URL.createObjectURL(await res.blob());
        if (cancelled) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        setPhoneShot({ status: 'ready', url: objectUrl });
      })
      .catch(() => {
        if (!cancelled) setPhoneShot({ status: 'error' });
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [isOpen, agency.id, demoId, previewVersion]);

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
        setError(outreachErrorMessage(res.status, await readDetail(res)));
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
        toast.error(res.status === 422 ? 'Check the texts: 3–6 services and no empty fields' : outreachErrorMessage(res.status, await readDetail(res)));
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

  const setPublished = async (publish: boolean) => {
    if (!publish && !window.confirm('Take the demo offline? The link in sent emails stops working.')) return;
    setBusy('publish');
    try {
      const res = await apiFetch(`/leads/${agency.id}/demo/${publish ? 'publish' : 'unpublish'}`, { method: 'POST' });
      if (!res.ok) {
        toast.error(outreachErrorMessage(res.status, await readDetail(res)));
        return;
      }
      applyDemo(await res.json());
      toast.success(publish ? 'Demo published' : 'Demo taken offline');
    } catch {
      toast.error('Failed to update publishing');
    } finally {
      setBusy(null);
    }
  };

  // Julkaisu ensin; vain onnistuneen julkaisun jälkeen sähköposti (ei koskaan linkitöntä luonnosta vahingossa)
  const publishAndCreateEmail = async () => {
    if (!demo || !onCreateEmail) return;
    if (demo.status === 'published') {
      onCreateEmail();
      return;
    }
    setBusy('publish');
    setError('');
    try {
      const res = await apiFetch(`/leads/${agency.id}/demo/publish`, { method: 'POST' });
      if (!res.ok) {
        const message = outreachErrorMessage(res.status, await readDetail(res));
        setError(message);
        toast.error(message);
        return;
      }
      applyDemo(await res.json());
      toast.success('Demo published');
      onCreateEmail();
    } catch {
      const message = 'Publishing failed. No email was created.';
      setError(message);
      toast.error(message);
    } finally {
      setBusy(null);
    }
  };

  const copyPublicUrl = async () => {
    if (!demo?.public_url) return;
    try {
      await navigator.clipboard.writeText(demo.public_url);
      toast.success('Link copied');
    } catch {
      toast.error('Failed to copy');
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

  const removePrice = (index: number) =>
    setDraft((d) =>
      d ? { ...d, services: d.services.map((s, i) => (i === index ? { ...s, price: null } : s)) } : d,
    );

  const currentTemplate = templates.find((t) => t.id === demo?.template);

  const labelClass = 'block text-2xs font-medium text-fg-muted';
  const secondaryButton =
    'inline-flex items-center justify-center gap-1.5 h-control-sm px-2.5 text-xs font-medium text-fg border border-line-strong hover:bg-raised rounded transition-colors disabled:opacity-60';

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
            aria-labelledby="demo-title"
            initial={{ opacity: 0, scale: 0.98, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.98, y: 8 }}
            transition={{ duration: 0.2 }}
            className="relative w-full max-w-6xl max-h-[92vh] bg-surface rounded-lg border border-line-strong shadow-overlay overflow-hidden flex flex-col"
          >
            <div className="flex items-center justify-between gap-3 px-5 py-3 border-b border-line">
              <div className="flex items-center gap-2.5 min-w-0">
                <LayoutTemplate size={16} className="shrink-0 text-fg-muted" />
                <div className="min-w-0">
                  <h3 id="demo-title" className="text-base font-semibold text-fg">Demo website</h3>
                  <p className="text-xs text-fg-subtle truncate">
                    {agency.name}
                    {demo ? ` · ${demo.status}` : ''}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {/* Pääpainike otsikkorivillä: näkyy aina, vaikka sivupaneelia vieritetään muokatessa */}
                {demo && onCreateEmail && (
                  <button
                    onClick={publishAndCreateEmail}
                    disabled={busy !== null}
                    className="inline-flex items-center gap-2 h-control px-3.5 text-sm font-medium text-accent-fg bg-accent hover:bg-accent-hover rounded transition-colors disabled:opacity-60"
                  >
                    {busy === 'publish' ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                    {demo.status === 'published' ? 'Create email with demo link' : 'Publish & create email'}
                  </button>
                )}
                <button
                  onClick={onClose}
                  aria-label="Close"
                  className="grid size-control-sm place-content-center rounded text-fg-subtle hover:text-fg hover:bg-raised transition-colors"
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto">
              {loading ? (
                <div role="status" className="flex items-center justify-center py-24">
                  <Loader2 size={20} className="animate-spin text-fg-subtle" />
                </div>
              ) : !demo ? (
                <div className="px-6 py-10 max-w-lg mx-auto text-center space-y-4">
                  <p className="text-sm text-fg-muted">
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
                  {error && <p role="alert" className="text-sm text-danger">{error}</p>}
                  <button
                    onClick={generate}
                    disabled={busy !== null}
                    className="inline-flex items-center gap-2 h-control px-4 text-sm font-medium text-accent-fg bg-accent hover:bg-accent-hover rounded transition-colors disabled:opacity-60"
                  >
                    {busy === 'generate' ? <Loader2 size={14} className="animate-spin" /> : <LayoutTemplate size={14} />}
                    {busy === 'generate' ? 'Generating...' : 'Generate demo'}
                  </button>
                </div>
              ) : (
                <div className="grid lg:grid-cols-[1fr_340px]">
                  <div className="p-4 bg-canvas border-b lg:border-b-0 lg:border-r border-line grid gap-4 xl:grid-cols-[1fr_auto] items-start">
                    {/* allow-scripts ilman allow-same-origin: aukiolo.js toimii, sivu pysyy eristettynä */}
                    <iframe
                      key={previewVersion}
                      title={`Demo preview: ${agency.name}`}
                      src={`${demo.preview_url}?v=${previewVersion}`}
                      sandbox="allow-scripts"
                      className="w-full h-[60vh] lg:h-[70vh] bg-canvas rounded border border-line"
                    />
                    <figure className="m-0 w-[234px] justify-self-center">
                      <figcaption className="flex items-center gap-1.5 mb-2 text-2xs font-medium text-fg-muted">
                        <Smartphone size={12} />
                        Phone, 390 px (first screen)
                      </figcaption>
                      <div className="w-[234px] h-[506px] overflow-hidden rounded border border-line bg-surface grid place-content-center">
                        {phoneShot.status === 'ready' && (
                          <img src={phoneShot.url} alt={`Phone view of the demo for ${agency.name}`} className="w-[234px] h-[506px] object-cover object-top" />
                        )}
                        {phoneShot.status === 'loading' && (
                          <span role="status" className="flex items-center gap-2 text-xs text-fg-subtle">
                            <Loader2 size={14} className="animate-spin" />
                            Rendering phone view...
                          </span>
                        )}
                        {phoneShot.status === 'unavailable' && (
                          <div className="w-[234px] h-[506px] overflow-hidden">
                            <iframe
                              key={`phone-${previewVersion}`}
                              title={`Phone preview: ${agency.name}`}
                              src={`${demo.preview_url}?v=${previewVersion}`}
                              sandbox="allow-scripts"
                              className="w-[390px] h-[844px] origin-top-left scale-[0.6] border-0"
                            />
                          </div>
                        )}
                        {phoneShot.status === 'error' && (
                          <p className="px-4 text-xs text-fg-subtle text-center">Phone view failed. Check the preview at 390 px in a new tab.</p>
                        )}
                      </div>
                    </figure>
                  </div>

                  <div className="p-4 space-y-4">
                    {error && (
                      <p role="alert" className="text-sm text-fg bg-danger/10 border border-danger/30 rounded px-3 py-2">
                        {error}
                      </p>
                    )}
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
                      <span className={`${labelClass} mb-1.5`}>
                        Hero image
                      </span>
                      {demo.content.images.options.length === 0 ? (
                        <p className="text-xs text-fg-subtle">
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
                                  className={`block w-full overflow-hidden rounded border transition-colors ${
                                    selected ? 'border-fg shadow-selected' : 'border-line hover:border-fg-subtle'
                                  }`}
                                >
                                  <img src={thumbUrl(photo)} alt={photo.alt} className="w-full h-16 object-cover" loading="lazy" />
                                </button>
                                <figcaption className="mt-0.5 text-2xs leading-tight text-fg-subtle truncate">
                                  <a href={withUtm(photo.photographer_url)} target="_blank" rel="noopener noreferrer" className="rounded-sm hover:text-fg hover:underline underline-offset-2">
                                    {photo.photographer_name}
                                  </a>{' '}
                                  /{' '}
                                  <a href={withUtm('https://unsplash.com/')} target="_blank" rel="noopener noreferrer" className="rounded-sm hover:text-fg hover:underline underline-offset-2">
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
                            className={`h-16 rounded border text-2xs font-medium text-fg-muted bg-raised ${
                              !demo.content.images.hero ? 'border-fg shadow-selected' : 'border-line hover:border-fg-subtle'
                            }`}
                          >
                            No photo
                          </button>
                        </div>
                      )}
                    </div>

                    {draft && (
                      <div className="space-y-3">
                        <label className={labelClass}>
                          Headline
                          <input
                            value={draft.hero_title}
                            onChange={(e) => setDraft({ ...draft, hero_title: e.target.value })}
                            maxLength={80}
                            className={`${inputClass} mt-1`}
                          />
                        </label>
                        <label className={labelClass}>
                          Subheadline
                          <input
                            value={draft.hero_subtitle}
                            onChange={(e) => setDraft({ ...draft, hero_subtitle: e.target.value })}
                            maxLength={180}
                            className={`${inputClass} mt-1`}
                          />
                        </label>
                        {templates.find((t) => t.id === demo.template)?.version === 2 && (
                          <label className={labelClass}>
                            About heading
                            <input
                              value={draft.about_title ?? ''}
                              onChange={(e) => setDraft({ ...draft, about_title: e.target.value.trim() ? e.target.value : null })}
                              maxLength={50}
                              className={`${inputClass} mt-1`}
                            />
                          </label>
                        )}
                        <label className={labelClass}>
                          About
                          <textarea
                            value={draft.about}
                            onChange={(e) => setDraft({ ...draft, about: e.target.value })}
                            maxLength={700}
                            rows={4}
                            className={`${inputClass} mt-1 resize-y`}
                          />
                        </label>

                        <div>
                          <div className="flex items-center justify-between mb-1">
                            <span className={labelClass}>
                              Services ({draft.services.length})
                            </span>
                            <div className="flex gap-1">
                              <button
                                type="button"
                                aria-label="Remove last service"
                                disabled={draft.services.length <= MIN_SERVICES}
                                onClick={() => setDraft({ ...draft, services: draft.services.slice(0, -1) })}
                                className="grid size-6 place-content-center rounded-sm text-fg-muted hover:text-fg hover:bg-raised disabled:opacity-30"
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
                                className="grid size-6 place-content-center rounded-sm text-fg-muted hover:text-fg hover:bg-raised disabled:opacity-30"
                              >
                                <Plus size={14} />
                              </button>
                            </div>
                          </div>
                          <div className="space-y-2">
                            {draft.services.map((s, i) => (
                              <div key={i} className="space-y-1 p-2 rounded border border-line">
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
                                {/* Hinta tulee vain yrityksen nykyiseltä sivulta: sen voi poistaa, ei kirjoittaa */}
                                {s.price && (
                                  <div className="flex items-center justify-between gap-2 text-xs text-fg-muted">
                                    <span>
                                      Price from their site: <span className="text-fg tabular-nums">{s.price}</span>
                                    </span>
                                    <button
                                      type="button"
                                      onClick={() => removePrice(i)}
                                      aria-label={`Remove price from service ${i + 1}`}
                                      className="h-control-sm px-2 rounded hover:bg-raised hover:text-fg transition-colors"
                                    >
                                      Remove price
                                    </button>
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>

                        <label className={labelClass}>
                          Prices note
                          <input
                            value={draft.price_note}
                            onChange={(e) => setDraft({ ...draft, price_note: e.target.value })}
                            maxLength={120}
                            className={`${inputClass} mt-1`}
                          />
                        </label>

                        <button
                          onClick={() => patch({ content: draft }, 'Texts saved')}
                          disabled={busy !== null}
                          className="w-full inline-flex items-center justify-center gap-2 h-control px-4 text-sm font-medium text-fg bg-raised border border-line-strong hover:border-fg-subtle rounded transition-colors disabled:opacity-60"
                        >
                          {busy === 'save' ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                          Save texts
                        </button>
                      </div>
                    )}

                    <div className="pt-3 border-t border-line space-y-2">
                      {demo.status === 'published' && demo.public_url ? (
                        <>
                          <div className="flex items-center gap-2 px-2.5 py-1.5 rounded border border-success/30 bg-success/10">
                            <Globe size={13} className="text-success shrink-0" />
                            <a
                              href={demo.public_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="rounded-sm text-xs text-fg font-medium truncate underline decoration-fg-subtle/40 underline-offset-2 hover:decoration-fg"
                            >
                              {demo.public_url}
                            </a>
                            <button
                              type="button"
                              onClick={copyPublicUrl}
                              aria-label="Copy public link"
                              className="ml-auto grid size-6 shrink-0 place-content-center rounded-sm text-fg-muted hover:text-fg hover:bg-raised"
                            >
                              <Copy size={13} />
                            </button>
                          </div>
                          {demo.expires_at && (
                            <p className="text-2xs text-fg-subtle">
                              Online until {new Date(demo.expires_at).toLocaleDateString('fi-FI')} (extended automatically if the lead is Hired)
                            </p>
                          )}
                          <button
                            onClick={() => setPublished(false)}
                            disabled={busy !== null}
                            className={`${secondaryButton} w-full`}
                          >
                            {busy === 'publish' ? <Loader2 size={13} className="animate-spin" /> : <EyeOff size={13} />}
                            Unpublish
                          </button>
                        </>
                      ) : (
                        <button
                          onClick={() => setPublished(true)}
                          disabled={busy !== null || !demo.publishing_enabled}
                          title={demo.publishing_enabled ? undefined : 'Set R2_* and DEMO_PUBLIC_BASE_URL in backend .env'}
                          className="w-full inline-flex items-center justify-center gap-2 h-control px-4 text-sm font-medium text-fg bg-raised border border-line-strong hover:border-fg-subtle rounded transition-colors disabled:opacity-50"
                        >
                          {busy === 'publish' ? <Loader2 size={14} className="animate-spin" /> : <Globe size={14} />}
                          {demo.status === 'expired' ? 'Publish again (30 days)' : 'Publish (30 days)'}
                        </button>
                      )}
                      {!demo.publishing_enabled && (
                        <p className="text-2xs text-fg-subtle">Publishing is not configured yet. Preview works locally.</p>
                      )}
                    </div>

                    <div className="flex flex-wrap gap-2">
                      <a
                        href={demo.preview_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={secondaryButton}
                      >
                        <ExternalLink size={13} />
                        Open in new tab
                      </a>
                      <button
                        onClick={generate}
                        disabled={busy !== null}
                        className={secondaryButton}
                      >
                        {busy === 'generate' ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                        Regenerate
                      </button>
                      <button
                        onClick={remove}
                        disabled={busy !== null}
                        className="inline-flex items-center gap-1.5 h-control-sm px-2.5 text-xs font-medium text-danger border border-danger/30 hover:bg-danger/10 rounded transition-colors disabled:opacity-60"
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
