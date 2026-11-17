import React, { useEffect, useState } from 'react';
import { AlertTriangle, ExternalLink, ListPlus, Loader2, Pencil, Plus, RotateCcw, Save, Trash2, UserCircle2, XCircle } from 'lucide-react';
import { toast } from 'sonner';
import type { DismissedPlace, SenderProfile, SenderProfileInput, ServiceCatalogItem } from '../types/agency';
import { apiFetch } from '../lib/api';
import { formatCents, formatVatRate, hundredthsToInput, parseDecimalToHundredths } from '../lib/quotes';

const EMPTY: SenderProfileInput = {
  name: '',
  company_name: '',
  brand_name: '',
  phone: '',
  website: '',
  short_intro: '',
  quote_terms: '',
  business_id: '',
};

const inputClass =
  'w-full h-control text-sm bg-canvas border border-line-strong rounded px-3 text-fg transition-colors';
const labelClass = 'block text-2xs font-medium text-fg-muted mb-1.5';

const dateFormat = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });

// Hylätyt paikat: kannassa on vain place_id (Googlen ehdot), joten nimen näkee Google Mapsista
const DismissedPlaces: React.FC = () => {
  const [places, setPlaces] = useState<DismissedPlace[]>([]);
  const [loading, setLoading] = useState(true);
  const [restoring, setRestoring] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await apiFetch('/places/dismissed');
        if (!res.ok) throw new Error(`${res.status}`);
        const data: DismissedPlace[] = await res.json();
        if (!cancelled) setPlaces(data);
      } catch {
        toast.error('Failed to load dismissed businesses');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const restore = async (placeId: string) => {
    setRestoring(placeId);
    try {
      const res = await apiFetch(`/places/${encodeURIComponent(placeId)}/dismiss`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`${res.status}`);
      setPlaces((prev) => prev.filter((p) => p.place_id !== placeId));
      toast.success('Restored. It can appear in searches again.');
    } catch {
      toast.error('Failed to restore');
    } finally {
      setRestoring(null);
    }
  };

  return (
    <section className="mt-6 bg-surface rounded border border-line" aria-labelledby="dismissed-title">
      <div className="flex items-center gap-2 px-card py-3 border-b border-line">
        <XCircle size={15} className="text-fg-muted" />
        <h2 id="dismissed-title" className="text-sm font-semibold text-fg">
          Dismissed businesses{' '}
          {!loading && <span className="text-fg-subtle font-normal tabular-nums">{places.length}</span>}
        </h2>
      </div>
      {loading ? (
        <div className="p-card flex justify-center">
          <Loader2 size={16} className="animate-spin text-fg-subtle" />
        </div>
      ) : places.length === 0 ? (
        <p className="p-card text-sm text-fg-subtle">
          Nothing dismissed. Businesses you dismiss in search results or the pipeline are listed here.
        </p>
      ) : (
        <ul className="divide-y divide-line">
          {places.map((place) => (
            <li key={place.place_id} className="flex items-center gap-3 px-card py-2.5">
              <a
                href={place.maps_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-sm text-fg hover:underline"
              >
                <ExternalLink size={13} className="text-fg-subtle" />
                View on Google Maps
              </a>
              <span className="text-xs text-fg-subtle tabular-nums">
                Dismissed {dateFormat.format(new Date(place.dismissed_at))}
              </span>
              <button
                type="button"
                onClick={() => restore(place.place_id)}
                disabled={restoring === place.place_id}
                className="ml-auto inline-flex items-center gap-1.5 h-control-sm px-2.5 text-xs font-medium text-fg border border-line-strong rounded hover:bg-raised transition-colors disabled:opacity-60"
              >
                {restoring === place.place_id ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
                Restore
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
};

interface CatalogForm {
  id: number | null;
  name: string;
  description: string;
  price: string;
  vat: string;
}

const EMPTY_CATALOG_FORM: CatalogForm = { id: null, name: '', description: '', price: '', vat: '25,5' };

// Palvelukatalogi: ainoa hintojen lähde tarjouksille. Hinnat alvittomina, alv-kanta per palvelu.
const ServiceCatalog: React.FC = () => {
  const [items, setItems] = useState<ServiceCatalogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState<CatalogForm | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await apiFetch('/service-catalog');
        if (!res.ok) throw new Error(`${res.status}`);
        const data: ServiceCatalogItem[] = await res.json();
        if (!cancelled) setItems(data);
      } catch {
        toast.error('Failed to load service catalog');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const edit = (item: ServiceCatalogItem) =>
    setForm({
      id: item.id,
      name: item.name,
      description: item.description ?? '',
      price: hundredthsToInput(item.unit_price_cents),
      vat: hundredthsToInput(item.vat_rate_bp),
    });

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form) return;
    const price = parseDecimalToHundredths(form.price);
    const vat = parseDecimalToHundredths(form.vat);
    if (!form.name.trim()) {
      toast.error('Service name is required');
      return;
    }
    if (price === null || vat === null || vat > 10000) {
      toast.error('Enter the price as euros (e.g. 390 or 390,50) and VAT as a percentage (0 to 100)');
      return;
    }
    setSaving(true);
    try {
      const res = await apiFetch(form.id === null ? '/service-catalog' : `/service-catalog/${form.id}`, {
        method: form.id === null ? 'POST' : 'PUT',
        body: JSON.stringify({
          name: form.name.trim(),
          description: form.description.trim() || null,
          unit_price_cents: price,
          vat_rate_bp: vat,
        }),
      });
      if (!res.ok) throw new Error(`${res.status}`);
      const saved: ServiceCatalogItem = await res.json();
      setItems((prev) => (form.id === null ? [...prev, saved] : prev.map((i) => (i.id === saved.id ? saved : i))));
      setForm(null);
      toast.success('Service saved. Existing quotes keep their own prices.');
    } catch {
      toast.error('Failed to save service');
    } finally {
      setSaving(false);
    }
  };

  const remove = async (item: ServiceCatalogItem) => {
    try {
      const res = await apiFetch(`/service-catalog/${item.id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`${res.status}`);
      setItems((prev) => prev.filter((i) => i.id !== item.id));
    } catch {
      toast.error('Failed to delete service');
    }
  };

  const field = (key: keyof CatalogForm) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((prev) => (prev ? { ...prev, [key]: e.target.value } : prev));

  return (
    <section className="mt-6 bg-surface rounded border border-line" aria-labelledby="catalog-title">
      <div className="flex items-center gap-2 px-card py-3 border-b border-line">
        <ListPlus size={15} className="text-fg-muted" />
        <h2 id="catalog-title" className="text-sm font-semibold text-fg">
          Service catalog
        </h2>
        <button
          type="button"
          onClick={() => setForm(EMPTY_CATALOG_FORM)}
          className="ml-auto inline-flex items-center gap-1.5 h-control-sm px-2.5 text-xs font-medium text-fg border border-line-strong rounded hover:bg-raised transition-colors"
        >
          <Plus size={12} />
          Add service
        </button>
      </div>
      <p className="px-card pt-3 text-xs text-fg-subtle">
        The only source of prices on quotes. Prices exclude VAT; VAT is added per service.
      </p>
      {form && (
        <form onSubmit={save} className="m-card p-card space-y-3 rounded border border-line bg-canvas">
          <div>
            <label htmlFor="catalog-name" className={labelClass}>
              Name *
            </label>
            <input id="catalog-name" value={form.name} onChange={field('name')} maxLength={120} className={inputClass} />
          </div>
          <div>
            <label htmlFor="catalog-description" className={labelClass}>
              Description
            </label>
            <input id="catalog-description" value={form.description} onChange={field('description')} maxLength={1000} className={inputClass} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="catalog-price" className={labelClass}>
                Price (€, excl. VAT) *
              </label>
              <input id="catalog-price" value={form.price} onChange={field('price')} inputMode="decimal" className={inputClass} placeholder="390" />
            </div>
            <div>
              <label htmlFor="catalog-vat" className={labelClass}>
                VAT % *
              </label>
              <input id="catalog-vat" value={form.vat} onChange={field('vat')} inputMode="decimal" className={inputClass} />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setForm(null)}
              className="h-control-sm px-3 text-xs font-medium text-fg border border-line-strong rounded hover:bg-raised transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="inline-flex items-center gap-1.5 h-control-sm px-3 bg-accent hover:bg-accent-hover text-accent-fg text-xs font-medium rounded transition-colors disabled:opacity-60"
            >
              {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
              Save service
            </button>
          </div>
        </form>
      )}
      {loading ? (
        <div className="p-card flex justify-center">
          <Loader2 size={16} className="animate-spin text-fg-subtle" />
        </div>
      ) : items.length === 0 ? (
        <p className="p-card text-sm text-fg-subtle">No services yet. Add the services you sell to create quotes.</p>
      ) : (
        <ul className="divide-y divide-line">
          {items.map((item) => (
            <li key={item.id} className="flex items-start gap-3 px-card py-2.5">
              <div className="min-w-0 flex-1">
                <p className="text-sm text-fg">{item.name}</p>
                {item.description && <p className="text-xs text-fg-subtle">{item.description}</p>}
              </div>
              <span className="shrink-0 text-sm text-fg tabular-nums">
                {formatCents(item.unit_price_cents)} <span className="text-xs text-fg-subtle">+ VAT {formatVatRate(item.vat_rate_bp)}</span>
              </span>
              <button
                type="button"
                onClick={() => edit(item)}
                aria-label={`Edit ${item.name}`}
                className="grid size-control-sm shrink-0 place-content-center rounded text-fg-subtle hover:text-fg hover:bg-raised transition-colors"
              >
                <Pencil size={13} />
              </button>
              <button
                type="button"
                onClick={() => remove(item)}
                aria-label={`Delete ${item.name}`}
                className="grid size-control-sm shrink-0 place-content-center rounded text-fg-subtle hover:text-danger hover:bg-danger/10 transition-colors"
              >
                <Trash2 size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
};

const SettingsView: React.FC = () => {
  const [form, setForm] = useState<SenderProfileInput>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [exists, setExists] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await apiFetch('/sender-profile');
        if (res.status === 404) return;
        if (!res.ok) throw new Error(`${res.status}`);
        const data: SenderProfile = await res.json();
        if (cancelled) return;
        setExists(true);
        setForm({
          name: data.name,
          company_name: data.company_name ?? '',
          brand_name: data.brand_name ?? '',
          phone: data.phone ?? '',
          website: data.website ?? '',
          short_intro: data.short_intro,
          quote_terms: data.quote_terms ?? '',
          business_id: data.business_id ?? '',
        });
      } catch {
        toast.error('Failed to load sender profile');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const update = (key: keyof SenderProfileInput) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((prev) => ({ ...prev, [key]: e.target.value }));

  const updateTerms = (e: React.ChangeEvent<HTMLTextAreaElement>) =>
    setForm((prev) => ({ ...prev, quote_terms: e.target.value }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim() || form.short_intro.trim().length < 5) {
      toast.error('Name and a short intro are required');
      return;
    }
    setSaving(true);
    try {
      const res = await apiFetch('/sender-profile', { method: 'PUT', body: JSON.stringify(form) });
      if (!res.ok) throw new Error(`${res.status}`);
      setExists(true);
      toast.success('Sender profile saved');
    } catch {
      toast.error('Failed to save sender profile');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div role="status" className="flex items-center justify-center py-24">
        <Loader2 size={20} className="animate-spin text-fg-subtle" />
      </div>
    );
  }

  return (
    <div className="max-w-2xl">
      <header className="mb-5">
        <h1 className="text-xl font-semibold tracking-tight text-fg">Settings</h1>
        <p className="text-sm text-fg-subtle mt-0.5">
          Your sender profile is used in AI emails and call scripts. The email signature is built from these fields.
        </p>
      </header>

      {!exists && (
        <div role="status" className="mb-4 px-3 py-2 rounded border border-warning/30 bg-warning/10 text-sm text-fg flex items-center gap-2">
          <AlertTriangle size={14} className="shrink-0 text-warning" />
          Fill in your sender profile before generating email drafts or call scripts.
        </div>
      )}

      <form onSubmit={handleSubmit} className="bg-surface rounded border border-line">
        <div className="flex items-center gap-2 px-card py-3 border-b border-line">
          <UserCircle2 size={15} className="text-fg-muted" />
          <h2 className="text-sm font-semibold text-fg">Sender profile</h2>
        </div>
        <div className="p-card space-y-3.5">
          <div>
            <label htmlFor="sender-name" className={labelClass}>
              Name *
            </label>
            <input id="sender-name" value={form.name} onChange={update('name')} maxLength={100} className={inputClass} placeholder="Matti Meikäläinen" />
          </div>
          <div>
            <label htmlFor="sender-intro" className={labelClass}>
              Short intro *
            </label>
            <input
              id="sender-intro"
              value={form.short_intro}
              onChange={update('short_intro')}
              maxLength={200}
              className={inputClass}
              placeholder="teen nettisivuja paikallisille yrityksille Espoossa"
              aria-describedby="sender-intro-help"
            />
            <p id="sender-intro-help" className="mt-1 text-xs text-fg-subtle">
              One sentence in Finnish, used as "who I am" in the first line of emails and calls.
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
            <div>
              <label htmlFor="sender-brand" className={labelClass}>
                Brand name
              </label>
              <input
                id="sender-brand"
                value={form.brand_name ?? ''}
                onChange={update('brand_name')}
                maxLength={60}
                className={inputClass}
                placeholder="Palin Web"
                aria-describedby="sender-brand-help"
              />
              <p id="sender-brand-help" className="mt-1 text-xs text-fg-subtle">
                Shown in the email signature next to your website.
              </p>
            </div>
            <div>
              <label htmlFor="sender-company" className={labelClass}>
                Company
              </label>
              <input
                id="sender-company"
                value={form.company_name ?? ''}
                onChange={update('company_name')}
                maxLength={100}
                className={inputClass}
                aria-describedby="sender-company-help"
              />
              <p id="sender-company-help" className="mt-1 text-xs text-fg-subtle">
                Official name. Used in the signature only if brand name is empty.
              </p>
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
            <div>
              <label htmlFor="sender-website" className={labelClass}>
                Portfolio website
              </label>
              <input id="sender-website" value={form.website ?? ''} onChange={update('website')} maxLength={200} className={inputClass} placeholder="https://..." />
            </div>
            <div>
              <label htmlFor="sender-phone" className={labelClass}>
                Phone
              </label>
              <input id="sender-phone" value={form.phone ?? ''} onChange={update('phone')} maxLength={40} className={inputClass} />
            </div>
          </div>
          <div>
            <label htmlFor="sender-business-id" className={labelClass}>
              Business ID (Y-tunnus)
            </label>
            <input id="sender-business-id" value={form.business_id ?? ''} onChange={update('business_id')} maxLength={20} className={inputClass} placeholder="1234567-8" />
          </div>
          <div>
            <label htmlFor="sender-terms" className={labelClass}>
              Quote terms
            </label>
            <textarea
              id="sender-terms"
              value={form.quote_terms ?? ''}
              onChange={updateTerms}
              maxLength={3000}
              rows={4}
              className="w-full text-sm bg-canvas border border-line-strong rounded px-3 py-2 text-fg transition-colors"
              aria-describedby="sender-terms-help"
            />
            <p id="sender-terms-help" className="mt-1 text-xs text-fg-subtle">
              Payment terms, delivery time and so on, shown on the quote page exactly as written. Empty = no terms section.
            </p>
          </div>
        </div>
        <div className="flex justify-end px-card py-3 border-t border-line">
          <button
            type="submit"
            disabled={saving}
            className="inline-flex items-center gap-2 h-control px-4 bg-accent hover:bg-accent-hover text-accent-fg text-sm font-medium rounded transition-colors disabled:opacity-60"
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            Save
          </button>
        </div>
      </form>

      <ServiceCatalog />

      <DismissedPlaces />
    </div>
  );
};

export default SettingsView;
