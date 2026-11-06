import React, { useState } from 'react';
import {
  ChevronsRight,
  Search,
  Layers,
  BarChart2,
  History,
  Settings,
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
    { id: 'search' as NavTab, icon: Search, label: 'Search' },
    {
      id: 'pipeline' as NavTab,
      icon: Layers,
      label: 'Pipeline',
      badge: savedAgencies.length,
    },
    {
      id: 'dashboard' as NavTab,
      icon: BarChart2,
      label: 'Dashboard',
    },
    { id: 'history' as NavTab, icon: History, label: 'History' },
    { id: 'settings' as NavTab, icon: Settings, label: 'Settings' },
  ];

  return (
    <motion.nav
      layout
      aria-label="Main"
      className="sticky top-0 h-screen shrink-0 border-r border-line bg-canvas p-2.5 flex flex-col"
      style={{
        width: open ? '216px' : 'fit-content',
      }}
    >
      <TitleSection open={open} />

      <div className="space-y-px">
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
      </div>

      <button
        onClick={onAddClick}
        title={open ? undefined : 'Add manually'}
        className="relative mt-3 flex h-control w-full items-center rounded border border-line-strong text-fg transition-colors hover:bg-raised"
      >
        <motion.div layout className="grid h-full w-9 place-content-center">
          <Plus className="size-4" />
        </motion.div>
        {open && (
          <motion.span
            layout
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.125 }}
            className="text-sm font-medium"
          >
            Add manually
          </motion.span>
        )}
      </button>

      <div className="mt-auto border-t border-line pt-2 space-y-px">
        <button
          onClick={() => signOut()}
          className="relative flex h-control w-full items-center rounded text-fg-muted transition-colors hover:bg-subtle hover:text-fg"
          title={user?.email ?? 'Sign out'}
          aria-label={`Sign out${user?.email ? ` (${user.email})` : ''}`}
        >
          <motion.div layout className="grid h-full w-9 place-content-center">
            <LogOut className="size-4" />
          </motion.div>
          {open && (
            <motion.span
              layout
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.125 }}
              className="text-sm truncate max-w-[140px]"
            >
              {user?.email ?? 'Sign out'}
            </motion.span>
          )}
        </button>
        <ToggleClose open={open} setOpen={setOpen} />
      </div>
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
      aria-current={selected ? 'page' : undefined}
      title={open ? undefined : title}
      className={`relative flex h-control w-full items-center rounded transition-colors ${
        selected
          ? 'bg-raised text-fg'
          : 'text-fg-muted hover:bg-subtle hover:text-fg'
      }`}
    >
      <motion.div layout className="grid h-full w-9 place-content-center">
        <Icon className="size-4" />
      </motion.div>
      {open && (
        <motion.span
          layout
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.125 }}
          className="text-sm font-medium"
        >
          {title}
        </motion.span>
      )}

      {badge !== undefined && badge > 0 && open && (
        <motion.span
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          style={{ y: '-50%' }}
          transition={{ delay: 0.5 }}
          className="absolute right-2.5 top-1/2 text-2xs tabular-nums text-fg-subtle"
        >
          {badge}
        </motion.span>
      )}
    </motion.button>
  );
};

const TitleSection: React.FC<{ open: boolean }> = ({ open }) => {
  return (
    <div className="mb-2.5 border-b border-line pb-2.5">
      <div className="flex items-center gap-2.5 px-1 py-0.5">
        <Logo />
        {open && (
          <motion.span
            layout
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.125 }}
            className="text-sm font-semibold text-fg"
          >
            Agency Hunter
          </motion.span>
        )}
      </div>
    </div>
  );
};

const Logo: React.FC = () => {
  return (
    <motion.div
      layout
      className="grid size-7 shrink-0 place-content-center rounded bg-accent"
    >
      <svg
        width="16"
        viewBox="0 0 50 39"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="fill-accent-fg"
        aria-hidden="true"
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
      aria-expanded={open}
      aria-label={open ? 'Collapse sidebar' : 'Expand sidebar'}
      className="relative flex h-control w-full items-center rounded text-fg-muted transition-colors hover:bg-subtle hover:text-fg"
    >
      <motion.div layout className="grid h-full w-9 place-content-center">
        <ChevronsRight
          className={`size-4 transition-transform ${open && 'rotate-180'}`}
        />
      </motion.div>
      {open && (
        <motion.span
          layout
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.125 }}
          className="text-sm"
        >
          Hide
        </motion.span>
      )}
    </motion.button>
  );
};

export default SidebarNav;
