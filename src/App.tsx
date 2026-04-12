import React, { useState, useEffect, useRef } from 'react';
import { Search, MapPin, Loader2, Filter, AlertTriangle, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import LeadTable from './components/LeadTable';
import SidebarNav from './components/SidebarNav';
import AddBusinessModal from './components/AddBusinessModal';
import type { NavTab } from './components/Navbar';
import PipelineBoard from './components/PipelineBoard';
import ComparisonView from './components/ComparisonView';
import HiringGuides from './components/HiringGuides';
import type { Agency } from './types/agency';
import { usePipeline } from './context/PipelineContext';

function App() {
  const [businessType, setBusinessType] = useState('autokorjaamo');
  const [city, setCity] = useState('Tampere');
  const [leads, setLeads] = useState<Agency[]>([]);
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
      toast.success(`${agency.name} saved to pipeline`);
    } catch {
      toast.error('Failed to save lead');
    }
  };

  const doSearch = async () => {
    if (!businessType || !city) {
      setError('Please fill in both fields.');
      return;
    }
    setLoading(true);
    setError('');
    setLeads([]);

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => {
      controller.abort();
    }, 60000);

    try {
      const response = await fetch(
        `http://127.0.0.1:8000/search?business_type=${encodeURIComponent(
          businessType,
        )}&city=${encodeURIComponent(city)}`,
        { signal: controller.signal },
      );
      window.clearTimeout(timeoutId);

      if (!response.ok) {
        throw new Error(`Virhe palvelimella: ${response.statusText}`);
      }

      const raw = (await response.json()) as Array<{
        name: string;
        place_id: string;
        address: string;
        phone?: string;
        website?: string;
        website_status: string;
        discovery_method: string;
      }>;

      const mapped: Agency[] = raw.map((item) => ({
        id: item.place_id,
        name: item.name,
        city: city,
        address: item.address,
        phone: item.phone,
        website: item.website ?? undefined,
        website_status: item.website_status,
        discovery_method: item.discovery_method,
      }));

      setLeads(mapped);
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
                    onClick={doSearch}
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
            </div>

            <LeadTable leads={filteredLeads} loading={loading} onSaveLead={handleSaveLead} />
          </>
        )}

        {activeTab === 'pipeline' && <PipelineBoard />}
        {activeTab === 'comparison' && <ComparisonView />}
        {activeTab === 'guides' && <HiringGuides />}
      </main>
    </div>
  );
}

export default App;