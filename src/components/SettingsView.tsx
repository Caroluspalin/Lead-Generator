import React, { useEffect, useState } from 'react';
import { Loader2, Save, UserCircle2 } from 'lucide-react';
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
  'w-full text-sm border-2 border-slate-200 rounded-lg px-4 py-2.5 text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 transition-colors';

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
      <div className="flex items-center justify-center py-24">
        <Loader2 size={24} className="animate-spin text-slate-400" />
      </div>
    );
  }

  return (
    <div className="max-w-2xl">
      <div className="mb-6 flex items-center gap-3">
        <div className="p-2 bg-indigo-100 rounded-lg">
          <UserCircle2 size={20} className="text-indigo-600" />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-slate-800">Sender profile</h2>
          <p className="text-sm text-slate-500">
            Used in AI emails and call scripts. The email signature is built from these fields.
          </p>
        </div>
      </div>

      {!exists && (
        <div className="mb-4 p-4 rounded-xl border border-amber-200 bg-amber-50 text-sm text-amber-800">
          Fill in your sender profile before generating email drafts or call scripts.
        </div>
      )}

      <form onSubmit={handleSubmit} className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6 space-y-4">
        <div>
          <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide mb-1.5">
            Name *
          </label>
          <input value={form.name} onChange={update('name')} maxLength={100} className={inputClass} placeholder="Matti Meikäläinen" />
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide mb-1.5">
            Short intro *
          </label>
          <input
            value={form.short_intro}
            onChange={update('short_intro')}
            maxLength={200}
            className={inputClass}
            placeholder="teen nettisivuja paikallisille yrityksille Espoossa"
          />
          <p className="mt-1 text-xs text-slate-400">
            One sentence in Finnish, used as "who I am" in the first line of emails and calls.
          </p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide mb-1.5">
              Company
            </label>
            <input value={form.company_name ?? ''} onChange={update('company_name')} maxLength={100} className={inputClass} />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide mb-1.5">
              Phone
            </label>
            <input value={form.phone ?? ''} onChange={update('phone')} maxLength={40} className={inputClass} />
          </div>
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide mb-1.5">
            Portfolio website
          </label>
          <input value={form.website ?? ''} onChange={update('website')} maxLength={200} className={inputClass} placeholder="https://..." />
        </div>
        <div className="flex justify-end">
          <button
            type="submit"
            disabled={saving}
            className="inline-flex items-center gap-2 px-6 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-xl shadow-sm shadow-indigo-200 transition-colors disabled:opacity-60"
          >
            {saving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
            Save
          </button>
        </div>
      </form>
    </div>
  );
};

export default SettingsView;
