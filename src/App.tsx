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
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <Loader2 size={28} className="animate-spin text-slate-400" />
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
    <div className="flex min-h-screen bg-slate-50 text-slate-900 font-sans">
      <SidebarNav
        activeTab={activeTab}
        onChangeTab={setActiveTab}
        onAddClick={() => setShowAddModal(true)}
      />
      <AddBusinessModal
        isOpen={showAddModal}
        onClose={() => setShowAddModal(false)}
      />

      <main className="flex-1 overflow-x-hidden px-4 sm:px-6 lg:px-8 py-8">
        {activeTab === 'search' && (
          <>
            <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6 mb-8">
              <form
                onSubmit={handleSearch}
                className="flex flex-col md:flex-row gap-4 items-end"
              >
                <div className="flex-1 w-full">
                  <label className="block text-sm font-medium text-slate-700 mb-1.5 ml-1">
                    Industry
                  </label>
                  <div className="relative group">
                    <Search
                      className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 group-focus-within:text-indigo-500 transition-colors"
                      size={18}
                    />
                    <input
                      type="text"
                      value={businessType}
                      onChange={(e) => setBusinessType(e.target.value)}
                      className="w-full pl-10 pr-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 outline-none transition-all"
                    />
                  </div>
                </div>

                <div className="flex-1 w-full">
                  <label className="block text-sm font-medium text-slate-700 mb-1.5 ml-1">
                    City
                  </label>
                  <div className="relative group">
                    <MapPin
                      className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 group-focus-within:text-indigo-500 transition-colors"
                      size={18}
                    />
                    <input
                      type="text"
                      value={city}
                      onChange={(e) => setCity(e.target.value)}
                      className="w-full pl-10 pr-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 outline-none transition-all"
                    />
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full md:w-auto px-8 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-xl shadow-sm shadow-indigo-200 active:scale-95 transition-all disabled:opacity-70 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                >
                  {loading ? (
                    <>
                      <Loader2 size={18} className="animate-spin" />
                      {loadingSeconds < 5
                        ? 'Scanning grid points...'
                        : loadingSeconds < 20
                          ? `Searching nearby businesses... ${loadingSeconds}s`
                          : `Analyzing websites... ${loadingSeconds}s`}
                    </>
                  ) : (
                    'Find Leads'
                  )}
                </button>
              </form>

              {error && (
                <div className="mt-4 p-4 bg-red-50 text-red-700 text-sm rounded-xl border border-red-100 flex items-center gap-3">
                  <AlertTriangle size={18} className="shrink-0 text-red-500" />
                  <span className="flex-1">{error}</span>
                  <button
                    type="button"
                    onClick={() => doSearch()}
                    className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-red-700 bg-red-100 hover:bg-red-200 rounded-lg transition-colors"
                  >
                    <RefreshCw size={12} />
                    Retry
                  </button>
                </div>
              )}
            </div>

            {/* Tulokset ja Filtteri */}
            <div className="mb-6 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <h2 className="text-lg font-semibold text-slate-800">
                  Results{' '}
                  <span className="text-slate-400 font-normal">
                    ({filteredLeads.length})
                  </span>
                </h2>
                <button
                  onClick={() =>
                    setShowOpportunitiesOnly(!showOpportunitiesOnly)
                  }
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors border ${
                    showOpportunitiesOnly
                      ? 'bg-indigo-50 text-indigo-700 border-indigo-200'
                      : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
                  }`}
                >
                  <Filter size={14} />
                  {showOpportunitiesOnly
                    ? 'Opportunities only'
                    : 'Show all'}
                </button>
              </div>
              {usage && (
                <span
                  className="text-xs text-slate-500 tabular-nums"
                  title={`Geocoding ${usage.geocode_calls}, Text Search ${usage.text_search_calls} (list price, before free tier)`}
                >
                  {usage.api_calls === 0
                    ? 'Mock data, 0 API calls'
                    : `${usage.api_calls} API calls, ~$${usage.estimated_cost_usd.toFixed(2)}`}
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