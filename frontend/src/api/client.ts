const API = '/api';

export interface StreamCallbacks {
  onEvent: (evt: any) => void;
  onError: (message: string) => void;
  onDone: () => void;
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

/** POST /chat/stream and parse the SSE frames from the response body. */
export async function streamChat(
  token: string,
  message: string,
  conversationId: string | null,
  cb: StreamCallbacks,
): Promise<string | null> {
  const res = await fetch(`${API}/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ message, conversationId }),
  });

  if (!res.ok || !res.body) {
    cb.onError(`Request failed (${res.status})`);
    return null;
  }
  const cid = res.headers.get('X-Conversation-Id') ?? conversationId;

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

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
  cb.onDone();
  return cid;
}
