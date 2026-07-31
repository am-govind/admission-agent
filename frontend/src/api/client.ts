import type { Conversation, ConversationDetail } from '../types';

const API = '/api';

export interface StreamCallbacks {
  onEvent: (evt: any) => void;
  onError: (message: string) => void;
  onDone: () => void;
}

/** Thrown for any non-OK response so callers can branch on 401 without parsing strings. */
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const isUnauthorized = (e: unknown) => e instanceof ApiError && e.status === 401;

async function request<T>(token: string, path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) throw new ApiError(res.status, `Request failed (${res.status})`);
  return (await res.json()) as T;
}

export async function login(username: string, password: string): Promise<string> {
  const res = await fetch(`${API}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new Error('Invalid username or password');
  const data = await res.json();
  return data.access_token as string;
}

export async function listConversations(token: string): Promise<Conversation[]> {
  const data = await request<{ conversations: Conversation[] }>(token, '/conversations');
  return data.conversations;
}

export function getConversation(token: string, id: string): Promise<ConversationDetail> {
  return request<ConversationDetail>(token, `/conversations/${id}`);
}

export function renameConversation(token: string, id: string, title: string) {
  return request<{ conversationId: string; title: string }>(token, `/conversations/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  });
}

export function deleteConversation(token: string, id: string) {
  return request<{ deleted: string }>(token, `/conversations/${id}`, { method: 'DELETE' });
}

/** POST /chat/stream and parse the SSE frames from the response body. */
export async function streamChat(
  token: string,
  message: string,
  conversationId: string | null,
  cb: StreamCallbacks,
  signal?: AbortSignal,
): Promise<string | null> {
  let res: Response;
  try {
    res = await fetch(`${API}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ message, conversationId }),
      signal,
    });
  } catch {
    // An abort is the user pressing Stop, not a failure worth surfacing.
    if (!signal?.aborted) cb.onError('Could not reach the server');
    cb.onDone();
    return null;
  }

  if (!res.ok || !res.body) {
    cb.onError(`Request failed (${res.status})`);
    cb.onDone();
    return null;
  }
  const cid = res.headers.get('X-Conversation-Id') ?? conversationId;

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE frames are separated by a blank line.
      let idx;
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const dataLine = frame.split('\n').find((l) => l.startsWith('data:'));
        if (!dataLine) continue;
        try {
          const payload = JSON.parse(dataLine.slice(5).trim());
          if (payload.type === 'run-error') {
            cb.onError(payload.error?.message ?? 'Unknown error');
          } else {
            cb.onEvent(payload);
          }
        } catch {
          // ignore malformed frame
        }
      }
    }
  } catch {
    if (!signal?.aborted) cb.onError('The connection dropped mid-answer');
  }
  cb.onDone();
  return cid;
}
