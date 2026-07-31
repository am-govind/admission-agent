import { useEffect, useRef, useState } from 'react';
import type { Conversation } from '../types';
import { CloseIcon, PencilIcon, PlusIcon, TrashIcon } from './Icons';

const DAY = 86_400_000;

/** Buckets a conversation list the way a person thinks about it, newest group first. */
function group(conversations: Conversation[]): [string, Conversation[]][] {
  const startOfToday = new Date().setHours(0, 0, 0, 0);
  const buckets = new Map<string, Conversation[]>();
  const order = ['Today', 'Yesterday', 'Previous 7 days', 'Previous 30 days', 'Older'];

  for (const c of conversations) {
    const ts = parseUtc(c.updatedAt);
    const age = startOfToday - new Date(ts).setHours(0, 0, 0, 0);
    const label =
      age <= 0 ? 'Today'
        : age <= DAY ? 'Yesterday'
          : age <= 7 * DAY ? 'Previous 7 days'
            : age <= 30 * DAY ? 'Previous 30 days'
              : 'Older';
    buckets.set(label, [...(buckets.get(label) ?? []), c]);
  }
  return order.filter((l) => buckets.has(l)).map((l) => [l, buckets.get(l)!]);
}

/** SQLite datetime('now') is UTC but has no zone suffix, so Date would read it as local. */
function parseUtc(value: string): number {
  const normalised = value.includes('T') ? value : value.replace(' ', 'T');
  return new Date(normalised.endsWith('Z') ? normalised : `${normalised}Z`).getTime();
}

export default function Sidebar({
  conversations, activeId, loading, open,
  onSelect, onNew, onRename, onDelete, onClose,
}: {
  conversations: Conversation[];
  activeId: string | null;
  loading: boolean;
  open: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [confirming, setConfirming] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // Escape unmounts the input, which can still fire onBlur; without this the abandoned
  // draft would be saved by the very keystroke meant to discard it.
  const cancelled = useRef(false);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  function startEditing(id: string, title: string) {
    cancelled.current = false;
    setDraft(title);
    setEditing(id);
  }

  function commit(id: string) {
    if (cancelled.current) return;
    const title = draft.trim();
    if (title && title !== conversations.find((c) => c.conversationId === id)?.title) {
      onRename(id, title);
    }
    setEditing(null);
  }

  const groups = group(conversations);

  return (
    <>
      <div
        onClick={onClose}
        className={`fixed inset-0 z-20 bg-slate-900/40 backdrop-blur-sm transition-opacity md:hidden ${
          open ? 'opacity-100' : 'pointer-events-none opacity-0'
        }`}
      />
      {/* Off-canvas on mobile, width-collapsed on desktop, so the toggle does something
          meaningful at both sizes. */}
      <aside
        className={`fixed inset-y-0 left-0 z-30 w-72 shrink-0 overflow-hidden border-r border-slate-200 bg-white transition-all duration-200 md:static md:translate-x-0 ${
          open ? 'translate-x-0 md:w-72' : '-translate-x-full md:w-0 md:border-r-0'
        }`}
      >
      <div className="flex h-full w-72 flex-col">
        <div className="flex items-center gap-2 p-3">
          <button
            onClick={onNew}
            className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-indigo-600 px-3 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-indigo-700"
          >
            <PlusIcon />
            New chat
          </button>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 md:hidden"
            aria-label="Close history"
          >
            <CloseIcon />
          </button>
        </div>

        <nav className="flex-1 space-y-4 overflow-y-auto px-2 pb-4">
          {loading && (
            <div className="space-y-2 px-1 pt-2">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="h-8 animate-pulse rounded-lg bg-slate-100" />
              ))}
            </div>
          )}

          {!loading && conversations.length === 0 && (
            <p className="px-3 pt-6 text-center text-xs leading-relaxed text-slate-400">
              Your past conversations will appear here.
            </p>
          )}

          {groups.map(([label, items]) => (
            <div key={label}>
              <p className="px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                {label}
              </p>
              <ul className="space-y-0.5">
                {items.map((c) => {
                  const active = c.conversationId === activeId;
                  return (
                    <li key={c.conversationId} className="group relative">
                      {editing === c.conversationId ? (
                        <input
                          ref={inputRef}
                          value={draft}
                          onChange={(e) => setDraft(e.target.value)}
                          onBlur={() => commit(c.conversationId)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') commit(c.conversationId);
                            if (e.key === 'Escape') {
                              cancelled.current = true;
                              setEditing(null);
                            }
                          }}
                          className="w-full rounded-lg border border-indigo-300 bg-white px-3 py-2 text-sm text-slate-800 focus:outline-none"
                        />
                      ) : (
                        <button
                          onClick={() => onSelect(c.conversationId)}
                          className={`flex w-full items-center rounded-lg px-3 py-2 text-left text-sm transition ${
                            active
                              ? 'bg-indigo-50 font-medium text-indigo-700'
                              : 'text-slate-600 hover:bg-slate-100'
                          }`}
                        >
                          <span className="truncate pr-12">{c.title}</span>
                        </button>
                      )}

                      {editing !== c.conversationId && confirming !== c.conversationId && (
                        <div className="absolute right-1 top-1/2 hidden -translate-y-1/2 items-center gap-0.5 group-hover:flex group-focus-within:flex">
                          <button
                            onClick={() => startEditing(c.conversationId, c.title)}
                            className="rounded-md p-1.5 text-slate-400 hover:bg-white hover:text-slate-700"
                            aria-label="Rename conversation"
                          >
                            <PencilIcon className="h-3.5 w-3.5" />
                          </button>
                          <button
                            onClick={() => setConfirming(c.conversationId)}
                            className="rounded-md p-1.5 text-slate-400 hover:bg-white hover:text-rose-600"
                            aria-label="Delete conversation"
                          >
                            <TrashIcon className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      )}

                      {confirming === c.conversationId && (
                        <div className="absolute inset-0 flex items-center justify-end gap-1 rounded-lg bg-rose-50 px-2 text-xs">
                          <span className="mr-auto pl-1 text-rose-700">Delete?</span>
                          <button
                            onClick={() => {
                              setConfirming(null);
                              onDelete(c.conversationId);
                            }}
                            className="rounded-md bg-rose-600 px-2 py-1 font-medium text-white hover:bg-rose-700"
                          >
                            Yes
                          </button>
                          <button
                            onClick={() => setConfirming(null)}
                            className="rounded-md px-2 py-1 text-rose-700 hover:bg-rose-100"
                          >
                            No
                          </button>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>
      </div>
      </aside>
    </>
  );
}
