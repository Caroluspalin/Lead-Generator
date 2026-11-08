import React, { useState, useEffect, useRef } from 'react';
import { Search, MapPin, Loader2, AlertTriangle, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import LeadTable from './components/LeadTable';
import SidebarNav from './components/SidebarNav';
import AddBusinessModal from './components/AddBusinessModal';
import type { NavTab } from './types/agency';
import PipelineBoard from './components/PipelineBoard';
import DashboardView from './components/DashboardView';
import SearchHistoryView from './components/SearchHistoryView';
import SettingsView from './components/SettingsView';
import type {
  Agency,
  SearchResponse,
  SearchStatusFilter,
  SearchSummary,
  SearchUsage,
} from './types/agency';
import { usePipeline } from './context/PipelineContext';
import { useAuth } from './context/AuthContext';
import { apiFetch } from './lib/api';
import Login from './components/Login';

const STATUS_FILTERS: { value: SearchStatusFilter; label: string }[] = [
  { value: 'no_website', label: 'No website' },
  { value: 'broken', label: 'Broken' },
  { value: 'insecure', label: 'No HTTPS' },
  { value: 'not_mobile', label: 'Not mobile' },
  { value: 'social_only', label: 'Social media only' },
];

// Haku jatkaa sivutusta ja analysoi sivuja kunnes määrä täyttyy, joten aikaa kuluu enemmän kuin yhteen hakuun
const SEARCH_TIMEOUT_MS = 180_000;

function summaryText(summary: SearchSummary): string {
  const found = `Found ${summary.found} of ${summary.requested} new leads`;
  if (summary.stop_reason === 'call_limit') {
    return `${found}. Stopped at the API call limit for one search.`;
  }
  if (summary.stop_reason === 'area_exhausted') {
    return summary.searched_neighbors
      ? `${found}. No more businesses in this city or the neighbouring areas.`
      : `${found}. No more businesses in this city. Include neighbouring areas to search further.`;
  }
  return `${found}.`;
}

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

  const [count, setCount] = useState(20);
  const [statusFilters, setStatusFilters] = useState<SearchStatusFilter[]>([]);
  const [minScore, setMinScore] = useState(0);
  const [excludeClosed, setExcludeClosed] = useState(false);
  const [onlyNew, setOnlyNew] = useState(true);
  const [expandNeighbors, setExpandNeighbors] = useState(false);
  const [summary, setSummary] = useState<SearchSummary | null>(null);

  const toggleStatus = (value: SearchStatusFilter) => {
    setStatusFilters((prev) =>
      prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value],
    );
  };

  const handleDismissLead = async (agency: Agency) => {
    try {
      const res = await apiFetch(`/places/${encodeURIComponent(agency.id)}/dismiss`, { method: 'POST' });
      if (!res.ok) throw new Error(res.statusText);
      setLeads((prev) => prev.filter((l) => l.id !== agency.id));
      toast.success(`${agency.name} dismissed`, {
        description: 'It will not appear in searches again. Restore it in Settings.',
      });
    } catch {
      toast.error('Failed to dismiss');
    }
  };

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
    setSummary(null);

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => {
      controller.abort();
    }, SEARCH_TIMEOUT_MS);

    try {
      const params = new URLSearchParams({
        business_type: bt,
        city: ct,
        count: String(count),
        min_score: String(minScore),
        exclude_closed: String(excludeClosed),
        only_new: String(onlyNew),
        expand_neighbors: String(expandNeighbors),
      });
      statusFilters.forEach((value) => params.append('status', value));
      const response = await apiFetch(`/search?${params.toString()}`, { signal: controller.signal });
      window.clearTimeout(timeoutId);

      if (!response.ok) {
        throw new Error(`Virhe palvelimella: ${response.statusText}`);
      }

      const data = (await response.json()) as SearchResponse;

      const mapped: Agency[] = data.results.map((item) => ({
        id: item.place_id,
        name: item.name,
        city: item.city ?? ct,
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
      setSummary(data.summary);
    } catch (err) {
      console.error(err);
      if ((err as DOMException).name === 'AbortError') {
        setError('Search timed out after 3 minutes. Try a smaller count or fewer filters.');
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
              <form onSubmit={handleSearch} className="flex flex-col gap-4">
              <div className="flex flex-col md:flex-row gap-2.5 items-end">
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
              </div>

              <div className="flex flex-col lg:flex-row lg:items-end gap-4 lg:gap-6">
                <div className="flex flex-wrap items-end gap-2.5">
                  <div>
                    <label htmlFor="search-count" className="block text-2xs font-medium text-fg-muted mb-1.5">
                      Leads
                    </label>
                    <input
                      id="search-count"
                      type="number"
                      min={1}
                      max={100}
                      value={count}
                      onChange={(e) => setCount(Math.min(100, Math.max(1, Number(e.target.value) || 1)))}
                      className="w-20 h-control px-2.5 bg-canvas border border-line-strong rounded text-sm text-fg tabular-nums"
                    />
                  </div>
                  <div>
                    <label htmlFor="search-min-score" className="block text-2xs font-medium text-fg-muted mb-1.5">
                      Min score
                    </label>
                    <input
                      id="search-min-score"
                      type="number"
                      min={0}
                      max={100}
                      step={5}
                      value={minScore}
                      onChange={(e) => setMinScore(Math.min(100, Math.max(0, Number(e.target.value) || 0)))}
                      className="w-20 h-control px-2.5 bg-canvas border border-line-strong rounded text-sm text-fg tabular-nums"
                    />
                  </div>
                </div>

                <fieldset className="min-w-0">
                  <legend className="block text-2xs font-medium text-fg-muted mb-1.5">
                    Website {statusFilters.length === 0 && <span className="text-fg-subtle font-normal">(any)</span>}
                  </legend>
                  <div className="flex flex-wrap gap-1.5">
                    {STATUS_FILTERS.map(({ value, label }) => {
                      const active = statusFilters.includes(value);
                      return (
                        <button
                          key={value}
                          type="button"
                          onClick={() => toggleStatus(value)}
                          aria-pressed={active}
                          className={`h-control-sm px-2.5 rounded text-xs font-medium transition-colors border ${
                            active
                              ? 'bg-raised text-fg border-line-strong'
                              : 'text-fg-muted border-line hover:text-fg hover:bg-subtle'
                          }`}
                        >
                          {label}
                        </button>
                      );
                    })}
                  </div>
                </fieldset>

                <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-fg-muted lg:pb-1.5">
                  <label className="inline-flex items-center gap-1.5 cursor-pointer">
                    <input type="checkbox" checked={onlyNew} onChange={(e) => setOnlyNew(e.target.checked)} />
                    Only new
                  </label>
                  <label className="inline-flex items-center gap-1.5 cursor-pointer">
                    <input type="checkbox" checked={excludeClosed} onChange={(e) => setExcludeClosed(e.target.checked)} />
                    Exclude closed
                  </label>
                  <label className="inline-flex items-center gap-1.5 cursor-pointer">
                    <input type="checkbox" checked={expandNeighbors} onChange={(e) => setExpandNeighbors(e.target.checked)} />
                    Include neighbouring areas
                  </label>
                </div>
              </div>
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

            {/* Tulokset ja hakuyhteenveto */}
            <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h2 className="text-sm font-semibold text-fg">
                  Results{' '}
                  <span className="text-fg-subtle font-normal tabular-nums">{leads.length}</span>
                </h2>
                {summary && (
                  <p className="text-xs text-fg-muted" role="status">
                    {summaryText(summary)}
                    {summary.skipped_in_pipeline + summary.skipped_dismissed + summary.skipped_seen > 0 && (
                      <span className="text-fg-subtle">
                        {' '}
                        Skipped {summary.skipped_in_pipeline} in pipeline, {summary.skipped_dismissed} dismissed
                        {summary.skipped_seen > 0 ? `, ${summary.skipped_seen} already seen` : ''}.
                      </span>
                    )}
                  </p>
                )}
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

            <LeadTable
              leads={leads}
              loading={loading}
              onSaveLead={handleSaveLead}
              onDismissLead={handleDismissLead}
            />
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