import React, { useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, FileText, Loader2, Copy, ExternalLink, Plus, Trash2, Send, Save, FilePlus2 } from 'lucide-react';
import { toast } from 'sonner';
import type { Quote, SavedAgency, ServiceCatalogItem } from '../types/agency';
import { apiFetch } from '../lib/api';
import { outreachErrorMessage, readDetail } from '../lib/apiErrors';
import { usePipeline } from '../context/PipelineContext';
import { parseUtc } from '../lib/followUps';
import { formatCents, formatVatRate, quoteStatusLabel, quoteTotals } from '../lib/quotes';

interface QuoteModalProps {
  isOpen: boolean;
  onClose: () => void;
  agency: SavedAgency;
}

interface EditorLine {
  itemId: string;
  quantity: string;
}

interface Editor {
  quoteId: number | null;
  lines: EditorLine[];
  validDays: string;
}

const dateTime = new Intl.DateTimeFormat('fi-FI', { dateStyle: 'medium', timeStyle: 'short' });

const fieldClass = 'text-sm bg-canvas border border-line-strong rounded px-2.5 text-fg transition-colors';
const secondaryButton =
  'inline-flex items-center justify-center gap-1.5 h-control-sm px-2.5 text-xs font-medium text-fg border border-line-strong rounded hover:bg-raised transition-colors disabled:opacity-60';

const QuoteModal: React.FC<QuoteModalProps> = ({ isOpen, onClose, agency }) => {
  const { refresh } = usePipeline();
  const [catalog, setCatalog] = useState<ServiceCatalogItem[]>([]);
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [editor, setEditor] = useState<Editor | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [catalogRes, quotesRes] = await Promise.all([apiFetch('/service-catalog'), apiFetch(`/leads/${agency.id}/quotes`)]);
      if (!catalogRes.ok || !quotesRes.ok) throw new Error('load failed');
      setCatalog(await catalogRes.json());
      const list: Quote[] = await quotesRes.json();
      setQuotes(list);
      return list;
    } catch {
      setError('Failed to load quotes. Is the backend running?');
      return [];
    } finally {
      setLoading(false);
    }
  }, [agency.id]);

  useEffect(() => {
    if (!isOpen) return;
    setEditor(null);
    void load();
  }, [isOpen, load]);

  const hasDraft = quotes.some((q) => q.status === 'draft');

  const startEditor = (quote?: Quote) => {
    if (!quote) {
      setEditor({ quoteId: null, lines: [{ itemId: catalog[0] ? String(catalog[0].id) : '', quantity: '1' }], validDays: '30' });
      return;
    }
    // Rivit ovat katalogin kopioita: vastaava katalogirivi haetaan nimellä, jotta muokkaus voi jatkua
    const lines = quote.lines.flatMap((line) => {
      const match = catalog.find((c) => c.name === line.name);
      return match ? [{ itemId: String(match.id), quantity: String(line.quantity) }] : [];
    });
    setEditor({ quoteId: quote.id, lines: lines.length ? lines : [{ itemId: '', quantity: '1' }], validDays: String(quote.valid_days) });
  };

  const editorLines = editor
    ? editor.lines.flatMap((line) => {
        const item = catalog.find((c) => String(c.id) === line.itemId);
        const quantity = Number(line.quantity);
        return item && Number.isInteger(quantity) && quantity >= 1 ? [{ ...item, quantity }] : [];
      })
    : [];
  const editorValid =
    editor !== null &&
    editorLines.length === editor.lines.length &&
    Number.isInteger(Number(editor.validDays)) &&
    Number(editor.validDays) >= 1 &&
    Number(editor.validDays) <= 365;
  const totals = quoteTotals(editorLines.map((l) => ({ unit_price_cents: l.unit_price_cents, quantity: l.quantity, vat_rate_bp: l.vat_rate_bp })));

  const failure = async (res: Response, fallback: string) => {
    const detail = await readDetail(res);
    toast.error(res.status === 409 || res.status === 428 || res.status === 503 ? outreachErrorMessage(res.status, detail) : fallback);
  };

  const saveDraft = async (): Promise<Quote | null> => {
    if (!editor || !editorValid) return null;
    const res = await apiFetch(editor.quoteId === null ? `/leads/${agency.id}/quotes` : `/quotes/${editor.quoteId}`, {
      method: editor.quoteId === null ? 'POST' : 'PUT',
      body: JSON.stringify({
        lines: editorLines.map((l) => ({ catalog_item_id: l.id, quantity: l.quantity })),
        valid_days: Number(editor.validDays),
      }),
    });
    if (!res.ok) {
      await failure(res, 'Failed to save the quote');
      return null;
    }
    return res.json();
  };

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
    } catch {
      toast.error('Something went wrong. Is the backend running?');
    } finally {
      setBusy(false);
    }
  };

  const handleSave = () =>
    run(async () => {
      const saved = await saveDraft();
      if (!saved) return;
      setEditor(null);
      await load();
      toast.success('Draft saved');
    });

  const sendQuote = async (id: number) => {
    const res = await apiFetch(`/quotes/${id}/send`, { method: 'POST' });
    if (!res.ok) {
      await failure(res, 'Failed to publish the quote');
      return false;
    }
    setEditor(null);
    await load();
    await refresh();
    toast.success('Quote published and locked. Lead value updated.');
    return true;
  };

  const handleSend = () =>
    run(async () => {
      const saved = await saveDraft();
      if (!saved) return;
      // Jos julkaisu epäonnistuu, luonnos on jo tallennettu: seuraava tallennus päivittää samaa riviä
      setEditor((prev) => (prev ? { ...prev, quoteId: saved.id } : prev));
      await sendQuote(saved.id);
    });

  const handleDelete = (id: number) =>
    run(async () => {
      const res = await apiFetch(`/quotes/${id}`, { method: 'DELETE' });
      if (!res.ok) {
        await failure(res, 'Failed to delete the draft');
        return;
      }
      await load();
      await refresh();
    });

  const handleNewVersion = (id: number) =>
    run(async () => {
      const res = await apiFetch(`/quotes/${id}/new-version`, { method: 'POST' });
      if (!res.ok) {
        await failure(res, 'Failed to create a new version');
        return;
      }
      const created: Quote = await res.json();
      const list = await load();
      startEditor(list.find((q) => q.id === created.id) ?? created);
    });

  const copyLink = async (url: string) => {
    try {
      await navigator.clipboard.writeText(url);
      toast.success('Quote link copied');
    } catch {
      toast.error('Could not copy the link');
    }
  };

  const setLine = (index: number, patch: Partial<EditorLine>) =>
    setEditor((prev) => (prev ? { ...prev, lines: prev.lines.map((l, i) => (i === index ? { ...l, ...patch } : l)) } : prev));

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
            aria-labelledby="quote-title"
            initial={{ opacity: 0, scale: 0.98, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.98, y: 8 }}
            transition={{ duration: 0.2 }}
            className="relative w-full max-w-2xl bg-surface rounded-lg border border-line-strong shadow-overlay overflow-hidden"
          >
            <div className="flex items-center justify-between gap-3 px-5 py-3.5 border-b border-line">
              <div className="flex items-center gap-2.5 min-w-0">
                <FileText size={16} className="shrink-0 text-fg-muted" />
                <div className="min-w-0">
                  <h3 id="quote-title" className="text-base font-semibold text-fg">
                    Quote
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

            <div className="px-5 py-4 max-h-[70vh] overflow-y-auto space-y-4">
              {loading ? (
                <div role="status" className="flex justify-center py-12">
                  <Loader2 size={20} className="animate-spin text-fg-subtle" />
                </div>
              ) : error ? (
                <p role="alert" className="text-sm text-danger">
                  {error}
                </p>
              ) : (
                <>
                  {catalog.length === 0 && (
                    <p role="status" className="px-3 py-2 rounded border border-warning/30 bg-warning/10 text-sm text-fg">
                      Add your services (name, price, VAT) under Settings → Service catalog first. Prices on quotes come only from there.
                    </p>
                  )}

                  {editor ? (
                    <div className="rounded border border-line-strong p-3 space-y-3">
                      <h4 className="text-sm font-semibold text-fg">{editor.quoteId === null ? 'New quote' : 'Edit draft'}</h4>
                      {editor.lines.map((line, index) => (
                        <div key={index} className="flex gap-2">
                          <select
                            value={line.itemId}
                            onChange={(e) => setLine(index, { itemId: e.target.value })}
                            aria-label={`Service ${index + 1}`}
                            className={`${fieldClass} h-control min-w-0 flex-1`}
                          >
                            <option value="">Select service…</option>
                            {catalog.map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.name} · {formatCents(c.unit_price_cents)} + VAT {formatVatRate(c.vat_rate_bp)}
                              </option>
                            ))}
                          </select>
                          <input
                            value={line.quantity}
                            onChange={(e) => setLine(index, { quantity: e.target.value })}
                            inputMode="numeric"
                            aria-label={`Quantity ${index + 1}`}
                            className={`${fieldClass} h-control w-16 text-center`}
                          />
                          <button
                            type="button"
                            onClick={() => setEditor((prev) => (prev ? { ...prev, lines: prev.lines.filter((_, i) => i !== index) } : prev))}
                            disabled={editor.lines.length === 1}
                            aria-label={`Remove line ${index + 1}`}
                            className="grid size-control place-content-center rounded text-fg-subtle hover:text-danger hover:bg-danger/10 transition-colors disabled:opacity-40"
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      ))}
                      <div className="flex flex-wrap items-center gap-3">
                        <button
                          type="button"
                          onClick={() => setEditor((prev) => (prev ? { ...prev, lines: [...prev.lines, { itemId: '', quantity: '1' }] } : prev))}
                          disabled={catalog.length === 0}
                          className={secondaryButton}
                        >
                          <Plus size={12} />
                          Add line
                        </button>
                        <label className="flex items-center gap-2 text-xs text-fg-muted">
                          Valid for
                          <input
                            value={editor.validDays}
                            onChange={(e) => setEditor((prev) => (prev ? { ...prev, validDays: e.target.value } : prev))}
                            inputMode="numeric"
                            className={`${fieldClass} h-control-sm w-14 text-center`}
                          />
                          days
                        </label>
                        <p className="ml-auto text-sm text-fg tabular-nums">
                          {formatCents(totals.net)} <span className="text-xs text-fg-subtle">+ VAT {formatCents(totals.vat)} = {formatCents(totals.gross)}</span>
                        </p>
                      </div>
                      <p className="text-2xs text-fg-subtle">
                        Publishing makes the link live, locks the content and sets the lead's Value to the total excluding VAT. A sent quote cannot be edited, only replaced by a new version.
                      </p>
                      <div className="flex flex-wrap justify-end gap-2">
                        <button type="button" onClick={() => setEditor(null)} className={secondaryButton}>
                          Cancel
                        </button>
                        <button type="button" onClick={handleSave} disabled={busy || !editorValid} className={secondaryButton}>
                          <Save size={12} />
                          Save draft
                        </button>
                        <button
                          type="button"
                          onClick={handleSend}
                          disabled={busy || !editorValid}
                          className="inline-flex items-center gap-1.5 h-control-sm px-3 bg-accent hover:bg-accent-hover text-accent-fg text-xs font-medium rounded transition-colors disabled:opacity-60"
                        >
                          {busy ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
                          Publish quote
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => startEditor()}
                      disabled={catalog.length === 0 || hasDraft || agency.do_not_contact}
                      title={hasDraft ? 'Finish or delete the existing draft first' : undefined}
                      className={secondaryButton}
                    >
                      <FilePlus2 size={13} />
                      New quote
                    </button>
                  )}

                  {quotes.length === 0 ? (
                    <p className="text-sm text-fg-subtle">No quotes yet.</p>
                  ) : (
                    <ul className="space-y-2.5">
                      {quotes.map((quote) => (
                        <li key={quote.id} className="rounded border border-line p-3">
                          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                            <span className="text-sm font-medium text-fg">Version {quote.version}</span>
                            <span className="rounded-sm bg-raised px-1.5 py-0.5 text-xs font-medium text-fg-muted">
                              {quoteStatusLabel(quote.status, quote.open_count)}
                            </span>
                            <span className="ml-auto text-sm text-fg tabular-nums">
                              {formatCents(quote.net_cents)} <span className="text-xs text-fg-subtle">+ VAT = {formatCents(quote.gross_cents)}</span>
                            </span>
                          </div>
                          <ul className="mt-1.5 text-xs text-fg-muted">
                            {quote.lines.map((line, i) => (
                              <li key={i}>
                                {line.quantity} × {line.name} · {formatCents(line.unit_price_cents)} (VAT {formatVatRate(line.vat_rate_bp)})
                              </li>
                            ))}
                          </ul>
                          {quote.status === 'accepted' && quote.accepted_at && (
                            <p className="mt-1.5 text-xs text-success">
                              Accepted by {quote.accepted_name} on {dateTime.format(parseUtc(quote.accepted_at))}
                            </p>
                          )}
                          {quote.status !== 'draft' && quote.open_count > 0 && quote.last_opened_at && (
                            <p className="mt-1 text-xs text-fg-subtle">
                              Opened {quote.open_count}× · last {dateTime.format(parseUtc(quote.last_opened_at))}
                            </p>
                          )}
                          {quote.valid_until && quote.status === 'sent' && (
                            <p className="mt-1 text-xs text-fg-subtle">Valid until {dateTime.format(parseUtc(quote.valid_until))}</p>
                          )}
                          <div className="mt-2 flex flex-wrap gap-2">
                            {quote.status === 'draft' && (
                              <>
                                <button type="button" onClick={() => startEditor(quote)} disabled={busy} className={secondaryButton}>
                                  Edit
                                </button>
                                <button type="button" onClick={() => handleDelete(quote.id)} disabled={busy} className={secondaryButton}>
                                  <Trash2 size={12} />
                                  Delete
                                </button>
                              </>
                            )}
                            {quote.public_url && quote.status !== 'draft' && (
                              <>
                                <button type="button" onClick={() => copyLink(quote.public_url ?? '')} className={secondaryButton}>
                                  <Copy size={12} />
                                  Copy link
                                </button>
                                <a
                                  href={`${quote.public_url}?preview=1`}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className={secondaryButton}
                                >
                                  <ExternalLink size={12} />
                                  Open
                                </a>
                              </>
                            )}
                            {quote.status !== 'draft' && !hasDraft && quote.id === quotes[0]?.id && (
                              <button type="button" onClick={() => handleNewVersion(quote.id)} disabled={busy || agency.do_not_contact} className={secondaryButton}>
                                <FilePlus2 size={12} />
                                New version
                              </button>
                            )}
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};

export default QuoteModal;
