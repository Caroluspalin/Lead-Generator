import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import type { ReactNode } from 'react';
import { toast } from 'sonner';
import type { Agency, Demo, SavedAgency, PipelineStatus } from '../types/agency';
import { apiFetch } from '../lib/api';
import { useAuth } from './AuthContext';
import type { SignalFilter } from '../lib/signals';
import { parseUtc } from '../lib/followUps';

interface PipelineContextValue {
  savedAgencies: SavedAgency[];
  loading: boolean;
  error: string;
  addToPipeline: (agency: Agency) => Promise<void>;
  updateStatus: (id: number, status: PipelineStatus) => Promise<void>;
  updateNotes: (id: number, notes: string) => Promise<void>;
  removeFromPipeline: (id: number) => Promise<void>;
  dismissFromPipeline: (agency: SavedAgency) => Promise<void>;
  findEmail: (id: number) => Promise<SavedAgency>;
  setDoNotContact: (id: number, value: boolean) => Promise<void>;
  runAutodemo: (id: number) => Promise<Demo>;
  markReviewed: (id: number) => Promise<void>;
  refreshTimma: (id: number) => Promise<void>;
  measureSpeed: (id: number) => Promise<void>;
  updateWebsite: (id: number, website: string | null) => Promise<SavedAgency>;
  updateDealAmounts: (
    id: number,
    amounts: { deal_value?: number | null; recurring_monthly?: number | null },
  ) => Promise<SavedAgency>;
  setDemoPublished: (id: number, value: boolean) => void;
  // Pipelinen "Demo published" -suodatin: täällä, jotta valinta säilyy välilehteä vaihdettaessa
  demoPublishedOnly: boolean;
  setDemoPublishedOnly: (value: boolean) => void;
  // Pipelinen ostosignaalisuodattimet (Slow / Old site / Few reviews), AND-ehto
  signalFilters: SignalFilter[];
  toggleSignalFilter: (filter: SignalFilter) => void;
  // Pipelinen "Opened first" -järjestys (demon avanneet ensin)
  openedFirst: boolean;
  setOpenedFirst: (value: boolean) => void;
  refresh: () => Promise<void>;
}

const PipelineContext = createContext<PipelineContextValue | undefined>(
  undefined,
);

export const PipelineProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const { session } = useAuth();
  const userId = session?.user.id ?? null;
  const [savedAgencies, setSavedAgencies] = useState<SavedAgency[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [demoPublishedOnly, setDemoPublishedOnly] = useState(false);
  const [openedFirst, setOpenedFirst] = useState(false);
  const [signalFilters, setSignalFilters] = useState<SignalFilter[]>([]);
  const toggleSignalFilter = useCallback((filter: SignalFilter) => {
    setSignalFilters((prev) => (prev.includes(filter) ? prev.filter((f) => f !== filter) : [...prev, filter]));
  }, []);
  // Käyttäjä, jonka liidit on ladattu. Myöhemmät haut päivittävät listan taustalla:
  // luurangot tai virhepaneeli sulkisivat avoimen modaalin ja nollaisivat scrollin.
  const loadedForRef = useRef<string | null>(null);

  // Tuo Workerin kirjaamat demoavaukset (palvelin throttlaa). Ei taustapollausta: kutsutaan listan haun yhteydessä.
  const syncOpens = useCallback(async () => {
    try {
      const res = await apiFetch(`/leads/sync-opens`, { method: 'POST' });
      if (!res.ok) return;
      const { new_opens }: { new_opens: { lead_id: number; name: string; count: number }[] } = await res.json();
      if (new_opens.length === 0) return;
      const listRes = await apiFetch(`/leads`);
      if (listRes.ok) setSavedAgencies(await listRes.json());
      const names = new_opens.map((o) => o.name).filter(Boolean);
      toast.success(
        new_opens.length === 1
          ? `${names[0] ?? 'A lead'} opened their demo`
          : `${new_opens.length} leads opened their demo`,
        { description: new_opens.length > 1 ? names.join(', ') : undefined },
      );
    } catch (err) {
      console.error('Failed to sync demo opens:', err);
    }
  }, []);

  // Vastaukset (IMAP) näkyvät vasta listan haussa: ilmoitus kerran per vastaus (viimeksi nähty selaimessa)
  const announceReplies = useCallback((leads: SavedAgency[]) => {
    const key = 'followup-replied-seen';
    let seen = 0;
    try {
      seen = Number(localStorage.getItem(key) ?? 0);
    } catch {
      return;
    }
    const repliedAt = (a: SavedAgency): number => (a.followup_replied_at ? parseUtc(a.followup_replied_at).getTime() : 0);
    const fresh = leads.filter((a) => repliedAt(a) > seen);
    if (fresh.length === 0) return;
    const latest = Math.max(...fresh.map(repliedAt));
    try {
      localStorage.setItem(key, String(latest));
    } catch {
      // toast näytetään silti
    }
    // Ensimmäisellä kerralla ei tulvita vanhoista vastauksista
    if (seen === 0) return;
    const names = fresh.map((a) => a.name);
    toast.success(fresh.length === 1 ? `${names[0]} replied` : `${fresh.length} leads replied`, {
      description: fresh.length > 1 ? names.join(', ') : 'Follow-ups stopped.',
    });
  }, []);

  const refresh = useCallback(async () => {
    if (!userId) {
      loadedForRef.current = null;
      setSavedAgencies([]);
      setLoading(false);
      return;
    }
    const firstLoad = loadedForRef.current !== userId;
    if (firstLoad) {
      setSavedAgencies([]);
      setLoading(true);
      setError('');
    }
    try {
      const res = await apiFetch(`/leads`);
      if (!res.ok) {
        throw new Error(`Palvelin palautti virheen: ${res.status}`);
      }
      const data: SavedAgency[] = await res.json();
      setSavedAgencies(data);
      announceReplies(data);
      loadedForRef.current = userId;
      setError('');
      if (data.some((a) => a.demo_published)) void syncOpens();
    } catch (err) {
      console.error('Failed to fetch leads:', err);
      if (firstLoad) {
        setError('Failed to load leads. Make sure the backend is running.');
      }
    } finally {
      if (firstLoad) {
        setLoading(false);
      }
    }
  }, [userId, syncOpens, announceReplies]);

  useEffect(() => {
    refresh();
    // Backend kirjaa vastaukset taustalla: haetaan lista harvakseltaan, jotta ilmoitus tulee ilman sivun latausta
    const timer = setInterval(() => void refresh(), 5 * 60 * 1000);
    return () => clearInterval(timer);
  }, [refresh]);

  // Muut liidivastaukset kuin GET /leads eivät sisällä demo_published-kenttää: yhdistetään, ei korvata
  const mergeLead = (updated: SavedAgency) => {
    setSavedAgencies((prev) => prev.map((a) => (a.id === updated.id ? { ...a, ...updated } : a)));
  };

  // Demo-ikkuna ja Autodemo pitävät demo_published-tiedon ajan tasalla ilman koko listan hakua.
  // Vakaa funktio: Demo-ikkunan lataus riippuu siitä.
  const setDemoPublished = useCallback((id: number, value: boolean) => {
    setSavedAgencies((prev) =>
      prev.some((a) => a.id === id && a.demo_published !== value)
        ? prev.map((a) => (a.id === id ? { ...a, demo_published: value } : a))
        : prev,
    );
  }, []);

  const addToPipeline = async (agency: Agency) => {
    const res = await apiFetch(`/leads`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: agency.name,
        city: agency.city,
        google_place_id: agency.id,
        address: agency.address,
        phone: agency.phone,
        website: agency.website,
        website_status: agency.website_status,
        website_issue: agency.website_issue,
        rating: agency.rating,
        review_count: agency.review_count,
        business_status: agency.business_status,
        primary_type: agency.primary_type,
        maps_url: agency.maps_url,
        pipeline_status: 'Shortlisted',
        source: agency.discovery_method === 'Manual Entry' ? 'MANUAL' : 'API',
      }),
    });
    if (!res.ok) {
      throw new Error(`Save failed: ${res.status}`);
    }
    const saved = await res.json();
    setSavedAgencies((prev) => [saved, ...prev]);
  };

  const updateStatus = async (id: number, status: PipelineStatus) => {
    const res = await apiFetch(`/leads/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pipeline_status: status }),
    });
    if (!res.ok) {
      throw new Error(`Status update failed: ${res.status}`);
    }
    const updated = await res.json();
    mergeLead(updated);
  };

  const updateNotes = async (id: number, notes: string) => {
    const res = await apiFetch(`/leads/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ notes }),
    });
    if (!res.ok) {
      throw new Error(`Notes update failed: ${res.status}`);
    }
    const updated = await res.json();
    mergeLead(updated);
  };

  // Etsii sähköpostin liidin omalta sivustolta (backend: etusivu + max 3 yhteystietosivua)
  const findEmail = async (id: number): Promise<SavedAgency> => {
    const res = await apiFetch(`/leads/${id}/find-email`, { method: 'POST' });
    if (!res.ok) {
      throw new Error(`Email search failed: ${res.status}`);
    }
    const updated: SavedAgency = await res.json();
    mergeLead(updated);
    return updated;
  };

  const setDoNotContact = async (id: number, value: boolean) => {
    const res = await apiFetch(`/leads/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ do_not_contact: value }),
    });
    if (!res.ok) {
      throw new Error(`Update failed: ${res.status}`);
    }
    const updated: SavedAgency = await res.json();
    mergeLead(updated);
  };

  // Timma-tiedot (jos on) + demo + julkaisu; backend merkitsee liidin tarkistettavaksi. Ei sähköpostia.
  const runAutodemo = async (id: number): Promise<Demo> => {
    const res = await apiFetch(`/leads/${id}/autodemo`, { method: 'POST' });
    if (!res.ok) {
      const body: { detail?: string } = await res.json().catch(() => ({}));
      throw new Error(body.detail ?? `Autodemo failed: ${res.status}`);
    }
    const demo: Demo = await res.json();
    setSavedAgencies((prev) =>
      prev.map((a) =>
        a.id === id ? { ...a, review_before_contact: true, demo_published: demo.status === 'published' } : a,
      ),
    );
    return demo;
  };

  const markReviewed = async (id: number) => {
    const res = await apiFetch(`/leads/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ review_before_contact: false }),
    });
    if (!res.ok) {
      throw new Error(`Update failed: ${res.status}`);
    }
    const updated: SavedAgency = await res.json();
    mergeLead(updated);
  };

  const refreshTimma = async (id: number) => {
    const res = await apiFetch(`/leads/${id}/timma/refresh`, { method: 'POST' });
    if (!res.ok) {
      const body: { detail?: string } = await res.json().catch(() => ({}));
      throw new Error(body.detail ?? `Timma refresh failed: ${res.status}`);
    }
    const updated: SavedAgency = await res.json();
    mergeLead(updated);
  };

  const measureSpeed = async (id: number) => {
    const res = await apiFetch(`/leads/${id}/measure-speed`, { method: 'POST' });
    if (!res.ok) {
      const body: { detail?: string } = await res.json().catch(() => ({}));
      throw new Error(res.status === 503 ? 'Speed test unavailable, try later' : body.detail ?? `Speed test failed: ${res.status}`);
    }
    const updated: SavedAgency = await res.json();
    mergeLead(updated);
  };

  // Backend muuttaa Timma-yrityssivun kanoniseen muotoon (https://timma.fi/yritys/slug), jolloin Refresh Timma näkyy
  const updateWebsite = async (id: number, website: string | null): Promise<SavedAgency> => {
    const res = await apiFetch(`/leads/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ website }),
    });
    if (!res.ok) {
      throw new Error(`Website update failed: ${res.status}`);
    }
    const updated: SavedAgency = await res.json();
    mergeLead(updated);
    return updated;
  };

  const updateDealAmounts = async (
    id: number,
    amounts: { deal_value?: number | null; recurring_monthly?: number | null },
  ): Promise<SavedAgency> => {
    const res = await apiFetch(`/leads/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(amounts),
    });
    if (!res.ok) {
      throw new Error(`Amount update failed: ${res.status}`);
    }
    const updated: SavedAgency = await res.json();
    mergeLead(updated);
    return updated;
  };

  const removeFromPipeline = async (id: number) => {
    const res = await apiFetch(`/leads/${id}`, {
      method: 'DELETE',
    });
    if (!res.ok) {
      throw new Error(`Delete failed: ${res.status}`);
    }
    setSavedAgencies((prev) => prev.filter((a) => a.id !== id));
  };

  // Pysyvä hylkäys: backend poistaa liidin (ja demon) ja merkitsee paikan hylätyksi
  const dismissFromPipeline = async (agency: SavedAgency) => {
    if (!agency.google_place_id) {
      throw new Error('Manual leads cannot be dismissed');
    }
    const res = await apiFetch(`/places/${encodeURIComponent(agency.google_place_id)}/dismiss`, {
      method: 'POST',
    });
    if (!res.ok) {
      throw new Error(`Dismiss failed: ${res.status}`);
    }
    setSavedAgencies((prev) => prev.filter((a) => a.id !== agency.id));
  };

  return (
    <PipelineContext.Provider
      value={{
        savedAgencies,
        loading,
        error,
        addToPipeline,
        updateStatus,
        updateNotes,
        removeFromPipeline,
        dismissFromPipeline,
        findEmail,
        setDoNotContact,
        runAutodemo,
        markReviewed,
        refreshTimma,
        measureSpeed,
        updateWebsite,
        updateDealAmounts,
        setDemoPublished,
        demoPublishedOnly,
        setDemoPublishedOnly,
        signalFilters,
        toggleSignalFilter,
        openedFirst,
        setOpenedFirst,
        refresh,
      }}
    >
      {children}
    </PipelineContext.Provider>
  );
};

// Hook kuuluu providerin kanssa samaan tiedostoon; fast refresh tekee vain täyden reloadin tälle tiedostolle.
// eslint-disable-next-line react-refresh/only-export-components
export const usePipeline = (): PipelineContextValue => {
  const ctx = useContext(PipelineContext);
  if (!ctx) {
    throw new Error('usePipeline must be used within a PipelineProvider');
  }
  return ctx;
};
