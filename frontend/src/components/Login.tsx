import { useState } from 'react';
import { login } from '../api/client';

export default function Login({ onAuth }: { onAuth: (token: string, user: string) => void }) {
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const token = await login(username, password);
      onAuth(token, username);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full items-center justify-center">
      <form onSubmit={submit} className="w-80 space-y-4 rounded-xl bg-white p-6 shadow-lg">
        <div>
          <h1 className="text-lg font-semibold text-slate-800">Admissions & Finance Agent</h1>
          <p className="text-sm text-slate-500">Sign in to continue</p>
        </div>
        <input
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          placeholder="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        <input
          type="password"
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-lg bg-indigo-600 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
