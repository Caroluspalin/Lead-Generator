import React, { useState } from 'react';
import {
  ChevronDown,
  ChevronsRight,
  Search,
  Layers,
  BarChart2,
  History,
  Plus,
  LogOut,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { usePipeline } from '../context/PipelineContext';
import { useAuth } from '../context/AuthContext';
import type { NavTab } from '../types/agency';

interface SidebarNavProps {
  activeTab: NavTab;
  onChangeTab: (tab: NavTab) => void;
  onAddClick: () => void;
}

const SidebarNav: React.FC<SidebarNavProps> = ({
  activeTab,
  onChangeTab,
  onAddClick,
}) => {
  const { signOut, user } = useAuth();
  const [open, setOpen] = useState(true);
  const { savedAgencies } = usePipeline();

  const navItems = [
    { id: 'search' as NavTab, icon: Search, label: 'Search Businesses' },
    {
      id: 'pipeline' as NavTab,
      icon: Layers,
      label: 'My Pipeline',
      badge: savedAgencies.length,
    },
    {
      id: 'dashboard' as NavTab,
      icon: BarChart2,
      label: 'Dashboard',
    },
    { id: 'history' as NavTab, icon: History, label: 'Search History' },
  ];

  return (
    <motion.nav
      layout
      className="sticky top-0 h-screen shrink-0 border-r border-slate-300 bg-white p-2"
      style={{
        width: open ? '225px' : 'fit-content',
      }}
    >
      <TitleSection open={open} />

      <div className="space-y-1">
        {navItems.map((item) => (
          <Option
            key={item.id}
            Icon={item.icon}
            title={item.label}
            selected={activeTab === item.id}
            setSelected={() => onChangeTab(item.id)}
            open={open}
            badge={item.badge}
          />
        ))}
        <button
          onClick={onAddClick}
          className="relative flex h-10 w-full items-center rounded-md bg-indigo-600 text-white transition-colors hover:bg-indigo-700"
        >
          <motion.div
            layout
            className="grid h-full w-10 place-content-center text-lg"
          >
            <Plus />
          </motion.div>
          {open && (
            <motion.span
              layout
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.125 }}
              className="text-xs font-medium"
            >
              Add Manually
            </motion.span>
          )}
        </button>

        <button
          onClick={() => signOut()}
          className="relative flex h-10 w-full items-center rounded-md text-slate-500 transition-colors hover:bg-slate-100 mt-2"
          title={user?.email ?? 'Sign out'}
        >
          <motion.div
            layout
            className="grid h-full w-10 place-content-center text-lg"
          >
            <LogOut />
          </motion.div>
          {open && (
            <motion.span
              layout
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.125 }}
              className="text-xs font-medium truncate max-w-[140px]"
            >
              {user?.email ?? 'Sign out'}
            </motion.span>
          )}
        </button>
      </div>

      <ToggleClose open={open} setOpen={setOpen} />
    </motion.nav>
  );
};

interface OptionProps {
  Icon: React.ComponentType<{ className?: string }>;
  title: string;
  selected: boolean;
  setSelected: () => void;
  open: boolean;
  badge?: number;
}

const Option: React.FC<OptionProps> = ({
  Icon,
  title,
  selected,
  setSelected,
  open,
  badge,
}) => {
  return (
    <motion.button
      layout
      onClick={setSelected}
      className={`relative flex h-10 w-full items-center rounded-md transition-colors ${
        selected
          ? 'bg-indigo-100 text-indigo-800'
          : 'text-slate-500 hover:bg-slate-100'
      }`}
    >
      <motion.div
        layout
        className="grid h-full w-10 place-content-center text-lg"
      >
        <Icon />
      </motion.div>
      {open && (
        <motion.span
          layout
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.125 }}
          className="text-xs font-medium"
        >
          {title}
        </motion.span>
      )}

      {badge !== undefined && badge > 0 && open && (
        <motion.span
          initial={{ scale: 0, opacity: 0 }}
          animate={{
            opacity: 1,
            scale: 1,
          }}
          style={{ y: '-50%' }}
          transition={{ delay: 0.5 }}
          className="absolute right-2 top-1/2 flex size-5 items-center justify-center rounded-full bg-indigo-500 text-[10px] font-semibold text-white"
        >
          {badge}
        </motion.span>
      )}
    </motion.button>
  );
};

const TitleSection: React.FC<{ open: boolean }> = ({ open }) => {
  return (
    <div className="mb-3 border-b border-slate-300 pb-3">
      <div className="flex cursor-pointer items-center justify-between rounded-md transition-colors hover:bg-slate-100">
        <div className="flex items-center gap-2">
          <Logo />
          {open && (
            <motion.div
              layout
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.125 }}
            >
              <span className="block text-xs font-semibold">Agency Hunter</span>
              <span className="block text-xs text-slate-500">Pro Plan</span>
            </motion.div>
          )}
        </div>
        {open && <ChevronDown className="mr-2" />}
      </div>
    </div>
  );
};

const Logo: React.FC = () => {
  return (
    <motion.div
      layout
      className="grid size-10 shrink-0 place-content-center rounded-md bg-indigo-600"
    >
      <svg
        width="24"
        viewBox="0 0 50 39"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="fill-slate-50"
      >
        <path
          d="M16.4992 2H37.5808L22.0816 24.9729H1L16.4992 2Z"
          stopColor="#000000"
        ></path>
        <path
          d="M17.4224 27.102L11.4192 36H33.5008L49 13.0271H32.7024L23.2064 27.102H17.4224Z"
          stopColor="#000000"
        ></path>
      </svg>
    </motion.div>
  );
};

const ToggleClose: React.FC<{
  open: boolean;
  setOpen: React.Dispatch<React.SetStateAction<boolean>>;
}> = ({ open, setOpen }) => {
  return (
    <motion.button
      layout
      onClick={() => setOpen((pv) => !pv)}
      className="absolute bottom-0 left-0 right-0 border-t border-slate-300 transition-colors hover:bg-slate-100"
    >
      <div className="flex items-center p-2">
        <motion.div
          layout
          className="grid size-10 place-content-center text-lg"
        >
          <ChevronsRight
            className={`transition-transform ${open && 'rotate-180'}`}
          />
        </motion.div>
        {open && (
          <motion.span
            layout
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.125 }}
            className="text-xs font-medium"
          >
            Hide
          </motion.span>
        )}
      </div>
    </motion.button>
  );
};

export default SidebarNav;
