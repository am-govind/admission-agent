import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import type { ChatMessage } from '../types';
import EmptyState from './EmptyState';
import MessageBubble from './MessageBubble';
import { ChevronDownIcon } from './Icons';

export interface MessageListHandle {
  scrollToBottom: (smooth?: boolean) => void;
}

const NEAR_BOTTOM_PX = 120;

function MessageList(
  { messages, loadingTranscript, onPick, onRetry }: {
    messages: ChatMessage[];
    loadingTranscript: boolean;
    onPick: (prompt: string) => void;
    onRetry: (prompt: string) => void;
  },
  ref: React.Ref<MessageListHandle>,
) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);

  const scrollToBottom = useCallback((smooth = true) => {
    const el = scrollRef.current;
    if (!el) return;
    requestAnimationFrame(() => {
      el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
    });
  }, []);

  // Auto-scrolling is only welcome while the user is already at the bottom; yanking the
  // view away from someone reading an earlier chart is the thing to avoid.
  useImperativeHandle(ref, () => ({
    scrollToBottom: (smooth = true) => {
      if (pinned) scrollToBottom(smooth);
    },
  }), [pinned, scrollToBottom]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
      setPinned(distance < NEAR_BOTTOM_PX);
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  return (
    <div className="relative min-h-0 flex-1">
      <div ref={scrollRef} className="h-full overflow-y-auto scroll-smooth">
        <div className="mx-auto max-w-3xl px-4 py-6">
          {loadingTranscript ? (
            <div className="space-y-4">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-20 animate-pulse rounded-2xl bg-white/70" />
              ))}
            </div>
          ) : messages.length === 0 ? (
            <EmptyState onPick={onPick} />
          ) : (
            <div className="space-y-5">
              {messages.map((m) => (
                <MessageBubble key={m.id} message={m} onRetry={onRetry} />
              ))}
            </div>
          )}
        </div>
      </div>

      {!pinned && messages.length > 0 && (
        <button
          onClick={() => scrollToBottom()}
          className="absolute bottom-4 left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 shadow-lg transition hover:text-slate-900"
        >
          <ChevronDownIcon className="h-3.5 w-3.5" />
          Jump to latest
        </button>
      )}
    </div>
  );
}

export default forwardRef(MessageList);
