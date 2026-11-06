import React, { useEffect, useState } from 'react';
import { AlertTriangle, Loader2, Save, UserCircle2 } from 'lucide-react';
import { toast } from 'sonner';
import type { SenderProfile, SenderProfileInput } from '../types/agency';
import { apiFetch } from '../lib/api';

const EMPTY: SenderProfileInput = {
  name: '',
  company_name: '',
  phone: '',
  website: '',
  short_intro: '',
};

const inputClass =
  'w-full h-control text-sm bg-canvas border border-line-strong rounded px-3 text-fg transition-colors';
const labelClass = 'block text-2xs font-medium text-fg-muted mb-1.5';

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
          phone: data.phone ?? '',
          website: data.website ?? '',
          short_intro: data.short_intro,
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
              <label htmlFor="sender-company" className={labelClass}>
                Company
              </label>
              <input id="sender-company" value={form.company_name ?? ''} onChange={update('company_name')} maxLength={100} className={inputClass} />
            </div>
            <div>
              <label htmlFor="sender-phone" className={labelClass}>
                Phone
              </label>
              <input id="sender-phone" value={form.phone ?? ''} onChange={update('phone')} maxLength={40} className={inputClass} />
            </div>
          </div>
          <div>
            <label htmlFor="sender-website" className={labelClass}>
              Portfolio website
            </label>
            <input id="sender-website" value={form.website ?? ''} onChange={update('website')} maxLength={200} className={inputClass} placeholder="https://..." />
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
    </div>
  );
};

export default SettingsView;
