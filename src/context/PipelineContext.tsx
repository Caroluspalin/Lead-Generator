import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import type { ReactNode } from 'react';
import type { Agency, Demo, SavedAgency, PipelineStatus } from '../types/agency';
import { apiFetch } from '../lib/api';
import { useAuth } from './AuthContext';

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
  refresh: () => Promise<void>;
}

const PipelineContext = createContext<PipelineContextValue | undefined>(
  undefined,
);

export const PipelineProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const { session } = useAuth();
  const [savedAgencies, setSavedAgencies] = useState<SavedAgency[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    if (!session) {
      setSavedAgencies([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch(`/leads`);
      if (!res.ok) {
        throw new Error(`Palvelin palautti virheen: ${res.status}`);
      }
      const data = await res.json();
      setSavedAgencies(data);
    } catch (err) {
      console.error('Failed to fetch leads:', err);
      setError('Failed to load leads. Make sure the backend is running.');
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    refresh();
  }, [refresh]);

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
    setSavedAgencies((prev) =>
      prev.map((a) => (a.id === id ? updated : a)),
    );
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
    setSavedAgencies((prev) =>
      prev.map((a) => (a.id === id ? updated : a)),
    );
  };

  // Etsii sähköpostin liidin omalta sivustolta (backend: etusivu + max 3 yhteystietosivua)
  const findEmail = async (id: number): Promise<SavedAgency> => {
    const res = await apiFetch(`/leads/${id}/find-email`, { method: 'POST' });
    if (!res.ok) {
      throw new Error(`Email search failed: ${res.status}`);
    }
    const updated: SavedAgency = await res.json();
    setSavedAgencies((prev) => prev.map((a) => (a.id === id ? updated : a)));
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
    setSavedAgencies((prev) => prev.map((a) => (a.id === id ? updated : a)));
  };

  // Timma-tiedot (jos on) + demo + julkaisu; backend merkitsee liidin tarkistettavaksi. Ei sähköpostia.
  const runAutodemo = async (id: number): Promise<Demo> => {
    const res = await apiFetch(`/leads/${id}/autodemo`, { method: 'POST' });
    if (!res.ok) {
      const body: { detail?: string } = await res.json().catch(() => ({}));
      throw new Error(body.detail ?? `Autodemo failed: ${res.status}`);
    }
    const demo: Demo = await res.json();
    setSavedAgencies((prev) => prev.map((a) => (a.id === id ? { ...a, review_before_contact: true } : a)));
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
    setSavedAgencies((prev) => prev.map((a) => (a.id === id ? updated : a)));
  };

  const refreshTimma = async (id: number) => {
    const res = await apiFetch(`/leads/${id}/timma/refresh`, { method: 'POST' });
    if (!res.ok) {
      const body: { detail?: string } = await res.json().catch(() => ({}));
      throw new Error(body.detail ?? `Timma refresh failed: ${res.status}`);
    }
    const updated: SavedAgency = await res.json();
    setSavedAgencies((prev) => prev.map((a) => (a.id === id ? updated : a)));
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
