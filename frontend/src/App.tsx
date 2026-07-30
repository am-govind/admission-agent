import { useState } from 'react';
import Chat from './components/Chat';
import Login from './components/Login';

export default function App() {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('token'));
  const [user, setUser] = useState<string | null>(() => localStorage.getItem('user'));

  function handleAuth(t: string, u: string) {
    localStorage.setItem('token', t);
    localStorage.setItem('user', u);
    setToken(t);
    setUser(u);
  }

  function logout() {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    setToken(null);
    setUser(null);
  }

  if (!token || !user) {
    return <Login onAuth={handleAuth} />;
  }
  return <Chat token={token} user={user} onLogout={logout} />;
}
