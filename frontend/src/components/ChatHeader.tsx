import { useEffect, useRef, useState } from 'react';
import { LogoutIcon, MenuIcon, SidebarIcon } from './Icons';

export default function ChatHeader({
  title, user, sidebarOpen, onToggleSidebar, onLogout,
}: {
  title: string;
  user: string;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  onLogout: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function onDown(e: MouseEvent) {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    }
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [menuOpen]);

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-slate-200 bg-white/80 px-4 backdrop-blur">
      <button
        onClick={onToggleSidebar}
        className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-800"
        aria-label={sidebarOpen ? 'Hide history' : 'Show history'}
      >
        <span className="md:hidden"><MenuIcon /></span>
        <span className="hidden md:block"><SidebarIcon className="h-5 w-5" /></span>
      </button>

      <div className="min-w-0 flex-1">
        <h1 className="truncate text-sm font-semibold text-slate-800">{title}</h1>
        <p className="text-[11px] text-slate-400">Admissions &amp; Finance Agent</p>
      </div>

      <div ref={menuRef} className="relative">
        <button
          onClick={() => setMenuOpen((o) => !o)}
          className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-500 text-sm font-semibold uppercase text-white shadow-sm"
          aria-label="Account menu"
        >
          {user.slice(0, 1)}
        </button>
        {menuOpen && (
          <div className="absolute right-0 top-11 z-20 w-52 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-lg">
            <p className="truncate px-3 py-2 text-xs text-slate-400">
              Signed in as <span className="font-medium text-slate-600">{user}</span>
            </p>
            <button
              onClick={onLogout}
              className="flex w-full items-center gap-2 border-t border-slate-100 px-3 py-2.5 text-left text-sm text-slate-700 hover:bg-slate-50"
            >
              <LogoutIcon />
              Sign out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
