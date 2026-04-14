import React from 'react';
import { Building2 } from 'lucide-react';
import { usePipeline } from '../context/PipelineContext';

type NavTab = 'search' | 'pipeline' | 'dashboard' | 'history';

interface NavbarProps {
  activeTab: NavTab;
  onChangeTab: (tab: NavTab) => void;
}

const Navbar: React.FC<NavbarProps> = ({ activeTab, onChangeTab }) => {
  const { savedAgencies } = usePipeline();

  const navItems: { id: NavTab; label: string }[] = [
    { id: 'search', label: 'Search Businesses' },
    { id: 'pipeline', label: 'My Pipeline' },
    { id: 'dashboard', label: 'Dashboard' },
    { id: 'history', label: 'Search History' },
  ];

  return (
    <header className="bg-white border-b border-slate-200 sticky top-0 z-10">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="bg-indigo-600 p-2 rounded-lg">
            <Building2 className="text-white" size={20} />
          </div>
          <span className="font-bold text-xl tracking-tight text-slate-900">
            Agency Hunter
          </span>
        </div>

        <nav className="hidden md:flex items-center gap-4 text-sm font-medium">
          {navItems.map((item) => {
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => onChangeTab(item.id)}
                className={`relative px-3 py-1.5 rounded-full transition-colors ${
                  isActive
                    ? 'bg-indigo-50 text-indigo-700'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
                }`}
              >
                {item.label}
                {item.id === 'pipeline' && (
                  <span className="ml-2 inline-flex items-center justify-center px-1.5 min-w-[1.5rem] h-5 rounded-full bg-indigo-600 text-white text-[10px] font-semibold">
                    {savedAgencies.length}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        <div className="md:hidden">
          {/* Simple mobile select for now */}
          <select
            value={activeTab}
            onChange={(e) => onChangeTab(e.target.value as NavTab)}
            className="text-sm border border-slate-200 rounded-lg px-2 py-1 bg-white"
          >
            {navItems.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </div>

        <div className="hidden sm:flex text-xs font-medium px-2 py-1 bg-emerald-50 text-emerald-700 border border-emerald-100 rounded-full">
          Google Maps API Active
        </div>
      </div>
    </header>
  );
};

export type { NavTab };
export default Navbar;

