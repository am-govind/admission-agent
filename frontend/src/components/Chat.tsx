import { useRef, useState } from 'react';
import { streamChat } from '../api/client';
import { emptyRenderState, reduceEvent } from '../state/renderState';
import type { ChatMessage } from '../types';
import RenderMessage from './blocks/RenderMessage';

const SUGGESTED = [
  'How many admissions this month for Pune?',
  'Show the day-on-day trend for Vijayawada Vidyapeeth',
  'Class-wise breakdown for Bengaluru',
  'What does ARPU mean?',
];

export default function Chat({ token, user, onLogout }: {
  token: string;
  user: string;
  onLogout: () => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const convId = useRef<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  function scrollToBottom() {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
    });
  }

  async function send(text: string) {
    if (!text.trim() || busy) return;
    setInput('');
    setBusy(true);

    const userMsg: ChatMessage = { id: crypto.randomUUID(), role: 'user', text };
    const asstId = crypto.randomUUID();
    const asstMsg: ChatMessage = {
      id: asstId,
      role: 'assistant',
      renderState: emptyRenderState(),
      loading: true,
      loadingMessage: 'Thinking…',
    };
    setMessages((m) => [...m, userMsg, asstMsg]);
    scrollToBottom();

    const update = (fn: (msg: ChatMessage) => ChatMessage) =>
      setMessages((m) => m.map((msg) => (msg.id === asstId ? fn(msg) : msg)));

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
          scrollToBottom();
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
        scrollToBottom();
      },
    });
    if (newCid) convId.current = newCid;
  }

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col">
      <header className="flex items-center justify-between px-4 py-3">
        <div>
          <h1 className="font-semibold text-slate-800">Admissions & Finance Agent</h1>
          <p className="text-xs text-slate-500">Signed in as {user}</p>
        </div>
        <button onClick={onLogout} className="text-sm text-slate-500 hover:text-slate-800">
          Sign out
        </button>
      </header>

      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto px-4 pb-4">
        {messages.length === 0 && (
          <div className="mt-10 text-center">
            <p className="text-slate-500">Ask about admissions, finance, retention, or ARPU.</p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {SUGGESTED.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="rounded-full border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:border-indigo-400"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg) =>
          msg.role === 'user' ? (
            <div key={msg.id} className="flex justify-end">
              <div className="max-w-[80%] rounded-2xl bg-indigo-600 px-4 py-2 text-sm text-white">
                {msg.text}
              </div>
            </div>
          ) : (
            <div key={msg.id} className="flex justify-start">
              <div className="max-w-[90%] rounded-2xl bg-white px-4 py-3 text-sm shadow-sm">
                {msg.loading && (
                  <p className="animate-pulse text-slate-500">{msg.loadingMessage}</p>
                )}
                {msg.error && <p className="text-red-600">{msg.error}</p>}
                {msg.renderState && <RenderMessage state={msg.renderState} />}
              </div>
            </div>
          ),
        )}
      </div>

      <div className="border-t border-slate-200 bg-white p-3">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
          className="flex items-center gap-2"
        >
          <input
            className="flex-1 rounded-full border border-slate-300 px-4 py-2 text-sm focus:border-indigo-400 focus:outline-none"
            placeholder="Ask a question about admissions, finance, or ARPU…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={busy}
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="rounded-full bg-indigo-600 px-5 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
