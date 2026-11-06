import React, { useState, useEffect, useRef } from 'react';
import { Search, MapPin, Loader2, Filter, AlertTriangle, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import LeadTable from './components/LeadTable';
import SidebarNav from './components/SidebarNav';
import AddBusinessModal from './components/AddBusinessModal';
import type { NavTab } from './types/agency';
import PipelineBoard from './components/PipelineBoard';
import DashboardView from './components/DashboardView';
import SearchHistoryView from './components/SearchHistoryView';
import SettingsView from './components/SettingsView';
import type { Agency, SearchResponse, SearchUsage } from './types/agency';
import { usePipeline } from './context/PipelineContext';
import { useAuth } from './context/AuthContext';
import { apiFetch } from './lib/api';
import Login from './components/Login';

function App() {
  const { session, loading: authLoading } = useAuth();

  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-canvas">
        <Loader2 size={24} className="animate-spin text-fg-subtle" />
      </div>
    );
  }

  if (!session) {
    return <Login />;
  }

  return <AppShell />;
}

function AppShell() {
  const [businessType, setBusinessType] = useState('autokorjaamo');
  const [city, setCity] = useState('Tampere');
  const [leads, setLeads] = useState<Agency[]>([]);
  const [usage, setUsage] = useState<SearchUsage | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingSeconds, setLoadingSeconds] = useState(0);
  const loadingTimerRef = useRef<number | null>(null);

  useEffect(() => {
    if (loading) {
      setLoadingSeconds(0);
      loadingTimerRef.current = window.setInterval(() => {
        setLoadingSeconds((s) => s + 1);
      }, 1000);
    } else {
      if (loadingTimerRef.current) {
        clearInterval(loadingTimerRef.current);
        loadingTimerRef.current = null;
      }
    }
    return () => {
      if (loadingTimerRef.current) clearInterval(loadingTimerRef.current);
    };
  }, [loading]);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState<NavTab>('pipeline');
  const [showAddModal, setShowAddModal] = useState(false);
  const { addToPipeline } = usePipeline();

  const [showOpportunitiesOnly, setShowOpportunitiesOnly] = useState(true);

  const handleSaveLead = async (agency: Agency) => {
    try {
      await addToPipeline(agency);
      setLeads((prev) =>
        prev.map((l) => (l.id === agency.id ? { ...l, already_saved: true } : l)),
      );
      toast.success(`${agency.name} saved to pipeline`);
    } catch {
      toast.error('Failed to save lead');
    }
  };

  const doSearch = async (overrideBt?: string, overrideCity?: string) => {
    const bt = overrideBt ?? businessType;
    const ct = overrideCity ?? city;
    if (!bt || !ct) {
      setError('Please fill in both fields.');
      return;
    }
    setLoading(true);
    setError('');
    setLeads([]);
    setUsage(null);

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => {
      controller.abort();
    }, 60000);

    try {
      const response = await apiFetch(
        `/search?business_type=${encodeURIComponent(
          bt,
        )}&city=${encodeURIComponent(ct)}`,
        { signal: controller.signal },
      );
      window.clearTimeout(timeoutId);

      if (!response.ok) {
        throw new Error(`Virhe palvelimella: ${response.statusText}`);
      }

      const data = (await response.json()) as SearchResponse;

      const mapped: Agency[] = data.results.map((item) => ({
        id: item.place_id,
        name: item.name,
        city: ct,
        address: item.address,
        phone: item.phone ?? undefined,
        website: item.website ?? undefined,
        website_status: item.website_status,
        website_issue: item.website_issue ?? undefined,
        discovery_method: item.discovery_method,
        rating: item.rating ?? undefined,
        review_count: item.review_count ?? undefined,
        business_status: item.business_status ?? undefined,
        primary_type: item.primary_type ?? undefined,
        maps_url: item.maps_url ?? undefined,
        lead_score: item.lead_score,
        already_saved: item.already_saved,
      }));

      setLeads(mapped);
      setUsage(data.usage);
    } catch (err) {
      console.error(err);
      if ((err as DOMException).name === 'AbortError') {
        setError('Search timed out after 60s. The city may be too large or Google API is throttling.');
      } else {
        setError('Search failed. Make sure the backend is running.');
      }
    } finally {
      window.clearTimeout(timeoutId);
      setLoading(false);
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    doSearch();
  };

  // "Myyntipaikat" = yritykset joilla ei ole toimivaa mobiilisivua (potentiaaliset asiakkaat)
  const filteredLeads = showOpportunitiesOnly
    ? leads.filter(lead => lead.website_status !== "WEBSITE OK")
    : leads;

  return (
    <div className="flex min-h-screen bg-canvas text-fg font-sans">
      <SidebarNav
        activeTab={activeTab}
        onChangeTab={setActiveTab}
        onAddClick={() => setShowAddModal(true)}
      />
      <AddBusinessModal
        isOpen={showAddModal}
        onClose={() => setShowAddModal(false)}
      />

      <main className="flex-1 min-w-0 overflow-x-hidden px-4 sm:px-page-x py-page-y">
        {activeTab === 'search' && (
          <>
            <header className="mb-5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h1 className="text-xl font-semibold tracking-tight text-fg">Search</h1>
              <p className="text-sm text-fg-subtle">Find local businesses with weak or missing websites</p>
            </header>

            <div className="bg-surface rounded border border-line p-card mb-6">
              <form
                onSubmit={handleSearch}
                className="flex flex-col md:flex-row gap-2.5 items-end"
              >
                <div className="flex-1 w-full">
                  <label htmlFor="search-industry" className="block text-2xs font-medium text-fg-muted mb-1.5">
                    Industry
                  </label>
                  <div className="relative">
                    <Search
                      className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-subtle"
                      size={14}
                    />
                    <input
                      id="search-industry"
                      type="text"
                      value={businessType}
                      onChange={(e) => setBusinessType(e.target.value)}
                      className="w-full h-control pl-8 pr-3 bg-canvas border border-line-strong rounded text-sm text-fg transition-colors"
                    />
                  </div>
                </div>

                <div className="flex-1 w-full">
                  <label htmlFor="search-city" className="block text-2xs font-medium text-fg-muted mb-1.5">
                    City
                  </label>
                  <div className="relative">
                    <MapPin
                      className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-subtle"
                      size={14}
                    />
                    <input
                      id="search-city"
                      type="text"
                      value={city}
                      onChange={(e) => setCity(e.target.value)}
                      className="w-full h-control pl-8 pr-3 bg-canvas border border-line-strong rounded text-sm text-fg transition-colors"
                    />
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full md:w-auto h-control px-4 bg-accent hover:bg-accent-hover text-accent-fg text-sm font-medium rounded transition-colors disabled:opacity-70 disabled:cursor-not-allowed flex items-center justify-center gap-2 whitespace-nowrap"
                >
                  {loading ? (
                    <>
                      <Loader2 size={14} className="animate-spin" />
                      {loadingSeconds < 5
                        ? 'Scanning grid points...'
                        : loadingSeconds < 20
                          ? `Searching nearby businesses... ${loadingSeconds}s`
                          : `Analyzing websites... ${loadingSeconds}s`}
                    </>
                  ) : (
                    'Find leads'
                  )}
                </button>
              </form>

              {error && (
                <div role="alert" className="mt-3 px-3 py-2 bg-danger/10 text-fg text-sm rounded border border-danger/30 flex items-center gap-3">
                  <AlertTriangle size={14} className="shrink-0 text-danger" />
                  <span className="flex-1">{error}</span>
                  <button
                    type="button"
                    onClick={() => doSearch()}
                    className="shrink-0 flex items-center gap-1.5 h-control-sm px-2.5 text-xs font-medium text-fg border border-line-strong hover:bg-raised rounded transition-colors"
                  >
                    <RefreshCw size={12} />
                    Retry
                  </button>
                </div>
              )}
            </div>

            {/* Tulokset ja Filtteri */}
            <div className="mb-2.5 flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <h2 className="text-sm font-semibold text-fg">
                  Results{' '}
                  <span className="text-fg-subtle font-normal tabular-nums">
                    {filteredLeads.length}
                  </span>
                </h2>
                <button
                  type="button"
                  onClick={() =>
                    setShowOpportunitiesOnly(!showOpportunitiesOnly)
                  }
                  aria-pressed={showOpportunitiesOnly}
                  className={`flex items-center gap-1.5 h-[26px] px-2.5 rounded text-xs font-medium transition-colors border ${
                    showOpportunitiesOnly
                      ? 'bg-raised text-fg border-line-strong'
                      : 'text-fg-muted border-line hover:text-fg hover:bg-subtle'
                  }`}
                >
                  <Filter size={12} />
                  {showOpportunitiesOnly
                    ? 'Opportunities only'
                    : 'Show all'}
                </button>
              </div>
              {usage && (
                <span
                  className="text-xs text-fg-subtle tabular-nums"
                  title={`Geocoding ${usage.geocode_calls}, Text Search ${usage.text_search_calls} (list price, before free tier)`}
                >
                  {usage.api_calls === 0
                    ? 'Mock data · 0 API calls'
                    : `${usage.api_calls} API calls · ~$${usage.estimated_cost_usd.toFixed(2)}`}
                </span>
              )}
            </div>

            <LeadTable leads={filteredLeads} loading={loading} onSaveLead={handleSaveLead} />
          </>
        )}

        {activeTab === 'pipeline' && <PipelineBoard />}
        {activeTab === 'dashboard' && <DashboardView />}
        {activeTab === 'settings' && <SettingsView />}
        {activeTab === 'history' && (
          <SearchHistoryView
            onReSearch={(bt, c) => {
              setBusinessType(bt);
              setCity(c);
              setActiveTab('search');
              doSearch(bt, c);
            }}
          />
        )}
      </main>
    </div>
  );
}

export default App;