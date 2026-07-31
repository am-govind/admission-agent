import { useCallback, useEffect, useRef, useState } from 'react';
import { getConversation, isUnauthorized, streamChat } from '../api/client';
import { useConversations } from '../hooks/useConversations';
import { emptyRenderState, reduceEvent } from '../state/renderState';
import type { ChatMessage, TranscriptMessage } from '../types';
import ChatHeader from './ChatHeader';
import ChatInput from './ChatInput';
import MessageList, { type MessageListHandle } from './MessageList';
import Sidebar from './Sidebar';

const NEW_CHAT_TITLE = 'New chat';

/** Turn a stored transcript back into the messages the live chat renders. */
function hydrate(transcript: TranscriptMessage[]): ChatMessage[] {
  const messages: ChatMessage[] = [];
  let lastPrompt: string | undefined;
  for (const [i, m] of transcript.entries()) {
    if (m.role === 'user') {
      lastPrompt = m.content;
      messages.push({ id: `h-${i}`, role: 'user', text: m.content });
    } else {
      messages.push({
        id: `h-${i}`,
        role: 'assistant',
        prompt: lastPrompt,
        // Pre-renderState answers have only prose; show it rather than an empty bubble.
        renderState: m.renderState ?? {
          parts: [{ type: 'text', id: `h-${i}-text`, content: m.content }],
          contentBlocks: {},
        },
      });
    }
  }
  return messages;
}

export default function Chat({ token, user, onLogout }: {
  token: string;
  user: string;
  onLogout: () => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [loadingTranscript, setLoadingTranscript] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 768);

  const listRef = useRef<MessageListHandle>(null);
  const abortRef = useRef<AbortController | null>(null);
  // The id a turn should attach to, kept outside state so a send never races a re-render.
  const convId = useRef<string | null>(null);

  const {
    conversations, activeId, setActiveId, loading, refresh, rename, remove,
  } = useConversations(token, onLogout);

  const openConversation = useCallback(
    async (id: string) => {
      convId.current = id;
      setActiveId(id);
      setLoadingTranscript(true);
      try {
        const detail = await getConversation(token, id);
        setMessages(hydrate(detail.messages));
        requestAnimationFrame(() => listRef.current?.scrollToBottom(false));
      } catch (e) {
        if (isUnauthorized(e)) onLogout();
        else setMessages([]);
      } finally {
        setLoadingTranscript(false);
      }
    },
    [token, setActiveId, onLogout],
  );

  // Restore whatever was open before the reload.
  const restored = useRef(false);
  useEffect(() => {
    if (restored.current || loading) return;
    restored.current = true;
    if (activeId) openConversation(activeId);
  }, [loading, activeId, openConversation]);

  function startNewChat() {
    abortRef.current?.abort();
    convId.current = null;
    setActiveId(null);
    setMessages([]);
    setBusy(false);
    if (window.innerWidth < 768) setSidebarOpen(false);
  }

  function deleteConversation(id: string) {
    // Without clearing the pointer, the next message would post to the deleted id and the
    // server would recreate the conversation from scratch.
    if (id === convId.current) {
      abortRef.current?.abort();
      convId.current = null;
      setMessages([]);
      setBusy(false);
    }
    remove(id);
  }

  function selectConversation(id: string) {
    if (id === activeId) return;
    abortRef.current?.abort();
    setBusy(false);
    openConversation(id);
    if (window.innerWidth < 768) setSidebarOpen(false);
  }

  async function send(text: string) {
    if (!text.trim() || busy) return;
    setBusy(true);

    const userMsg: ChatMessage = { id: crypto.randomUUID(), role: 'user', text };
    const asstId = crypto.randomUUID();
    setMessages((m) => [...m, userMsg, {
      id: asstId,
      role: 'assistant',
      prompt: text,
      renderState: emptyRenderState(),
      loading: true,
      loadingMessage: 'Thinking…',
    }]);
    listRef.current?.scrollToBottom();

    const update = (fn: (msg: ChatMessage) => ChatMessage) =>
      setMessages((m) => m.map((msg) => (msg.id === asstId ? fn(msg) : msg)));

    const controller = new AbortController();
    abortRef.current = controller;
    const wasNew = convId.current === null;

    const newCid = await streamChat(token, text, convId.current, {
      onEvent: (evt) => {
        if (evt.type === 'run-started' || evt.type === 'thinking-start') {
          update((msg) => ({ ...msg, loading: true, loadingMessage: 'Thinking…' }));
        } else if (evt.type === 'processing-status') {
          update((msg) => ({ ...msg, loading: true, loadingMessage: evt.message }));
        } else if (
          evt.type === 'text-message-start' ||
          evt.type === 'text-message-content' ||
          evt.type === 'state-delta'
        ) {
          update((msg) => ({
            ...msg,
            loading: false,
            renderState: reduceEvent(msg.renderState ?? emptyRenderState(), evt),
          }));
          listRef.current?.scrollToBottom();
        }
      },
      onError: (message) => {
        if (message.includes('401')) {
          onLogout();
          return;
        }
        update((msg) => ({ ...msg, loading: false, error: message }));
      },
      onDone: () => {
        update((msg) => ({ ...msg, loading: false }));
        setBusy(false);
        listRef.current?.scrollToBottom();
      },
    }, controller.signal);

    if (abortRef.current === controller) abortRef.current = null;

    // An aborted turn may still resolve with its id; adopting it would drag the user back
    // to a conversation they have already navigated away from.
    if (newCid && !controller.signal.aborted) {
      convId.current = newCid;
      setActiveId(newCid);
    }
    // The list needs the new title on the first turn, and the new ordering after any turn.
    if (newCid || wasNew) refresh();
  }

  function stop() {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
    // The turn still completes server-side, so the stored answer is the full one.
    refresh();
  }

  function retry(prompt: string) {
    if (busy) return;
    send(prompt);
  }

  const title = activeId
    ? conversations.find((c) => c.conversationId === activeId)?.title ?? NEW_CHAT_TITLE
    : NEW_CHAT_TITLE;

  return (
    <div className="flex h-full overflow-hidden bg-slate-50">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        loading={loading}
        open={sidebarOpen}
        onSelect={selectConversation}
        onNew={startNewChat}
        onRename={rename}
        onDelete={deleteConversation}
        onClose={() => setSidebarOpen(false)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <ChatHeader
          title={title}
          user={user}
          sidebarOpen={sidebarOpen}
          onToggleSidebar={() => setSidebarOpen((o) => !o)}
          onLogout={onLogout}
        />
        <MessageList
          ref={listRef}
          messages={messages}
          loadingTranscript={loadingTranscript}
          onPick={send}
          onRetry={retry}
        />
        <ChatInput busy={busy} disabled={loadingTranscript} onSend={send} onStop={stop} />
      </div>
    </div>
  );
}
