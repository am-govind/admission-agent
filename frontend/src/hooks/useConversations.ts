import { useCallback, useEffect, useRef, useState } from 'react';
import {
  deleteConversation,
  isUnauthorized,
  listConversations,
  renameConversation,
} from '../api/client';
import type { Conversation } from '../types';

const ACTIVE_KEY = 'activeConversationId';

/** Signing out has to drop this, or the next user to sign in inherits the pointer. */
export function clearActiveConversation() {
  localStorage.removeItem(ACTIVE_KEY);
}

/** Owns the sidebar list and which conversation is open, including across reloads. */
export function useConversations(token: string, onUnauthorized: () => void) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(
    () => localStorage.getItem(ACTIVE_KEY),
  );
  const [loading, setLoading] = useState(true);
  const validated = useRef(false);

  useEffect(() => {
    if (activeId) localStorage.setItem(ACTIVE_KEY, activeId);
    else localStorage.removeItem(ACTIVE_KEY);
  }, [activeId]);

  const refresh = useCallback(async () => {
    try {
      setConversations(await listConversations(token));
    } catch (e) {
      if (isUnauthorized(e)) onUnauthorized();
    } finally {
      setLoading(false);
    }
  }, [token, onUnauthorized]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // The restored id may name a conversation that has since been deleted. Checked once,
  // on the first load only: after that a missing id just means a turn is still in flight.
  useEffect(() => {
    if (loading || validated.current) return;
    validated.current = true;
    if (activeId && !conversations.some((c) => c.conversationId === activeId)) {
      setActiveId(null);
    }
  }, [loading, activeId, conversations]);

  const rename = useCallback(
    async (id: string, title: string) => {
      setConversations((cs) =>
        cs.map((c) => (c.conversationId === id ? { ...c, title } : c)),
      );
      try {
        await renameConversation(token, id, title);
      } catch (e) {
        if (isUnauthorized(e)) onUnauthorized();
        refresh();
      }
    },
    [token, onUnauthorized, refresh],
  );

  const remove = useCallback(
    async (id: string) => {
      setConversations((cs) => cs.filter((c) => c.conversationId !== id));
      if (id === activeId) setActiveId(null);
      try {
        await deleteConversation(token, id);
      } catch (e) {
        if (isUnauthorized(e)) onUnauthorized();
        refresh();
      }
    },
    [token, activeId, onUnauthorized, refresh],
  );

  return { conversations, activeId, setActiveId, loading, refresh, rename, remove };
}
