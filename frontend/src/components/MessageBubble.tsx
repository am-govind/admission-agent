import { useState } from 'react';
import type { ChatMessage, RenderState } from '../types';
import RenderMessage from './blocks/RenderMessage';
import { CheckIcon, CopyIcon, RetryIcon, SparkIcon } from './Icons';

/** The prose of an answer, so "copy" yields text rather than the render model. */
function plainText(state: RenderState | undefined): string {
  if (!state) return '';
  return state.parts
    .filter((p): p is Extract<typeof p, { type: 'text' }> => p.type === 'text')
    .map((p) => p.content)
    .join('\n\n')
    .trim();
}

function TypingIndicator({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2.5 py-0.5">
      <span className="flex gap-1">
        {[0, 150, 300].map((delay) => (
          <span
            key={delay}
            className="h-1.5 w-1.5 animate-bounce rounded-full bg-indigo-400"
            style={{ animationDelay: `${delay}ms` }}
          />
        ))}
      </span>
      <span className="text-sm text-slate-500">{label || 'Thinking…'}</span>
    </div>
  );
}

export default function MessageBubble({
  message, onRetry,
}: {
  message: ChatMessage;
  onRetry?: (prompt: string) => void;
}) {
  const [copied, setCopied] = useState(false);

  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-indigo-600 px-4 py-2.5 text-sm leading-relaxed text-white shadow-sm">
          {message.text}
        </div>
      </div>
    );
  }

  const text = plainText(message.renderState);
  const showActions = !message.loading && (text || message.error);

  async function copy() {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  }

  return (
    <div className="group flex gap-3">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-500 text-white shadow-sm">
        <SparkIcon className="h-4 w-4" />
      </div>

      <div className="min-w-0 flex-1">
        <div className="rounded-2xl rounded-tl-md border border-slate-200/80 bg-white px-4 py-3 shadow-sm">
          {message.loading && <TypingIndicator label={message.loadingMessage} />}
          {message.error && (
            <p className="text-sm text-rose-600">{message.error}</p>
          )}
          {message.renderState && message.renderState.parts.length > 0 && (
            <RenderMessage state={message.renderState} />
          )}
        </div>

        {showActions && (
          <div className="mt-1 flex items-center gap-1 transition-opacity md:opacity-0 md:focus-within:opacity-100 md:group-hover:opacity-100">
            {text && (
              <button
                onClick={copy}
                className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              >
                {copied ? <CheckIcon className="h-3.5 w-3.5" /> : <CopyIcon className="h-3.5 w-3.5" />}
                {copied ? 'Copied' : 'Copy'}
              </button>
            )}
            {onRetry && message.prompt && (
              <button
                onClick={() => onRetry(message.prompt!)}
                className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              >
                <RetryIcon className="h-3.5 w-3.5" />
                Retry
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
