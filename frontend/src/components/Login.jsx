import { useState } from 'react';
import { ArrowRight, Eye, EyeOff, LockKeyhole } from 'lucide-react';
import Brand from './Brand';
import './Login.css';

export default function Login({ allowSignup, onSubmit, error, busy }) {
  const [mode, setMode] = useState('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const handleSubmit = (event) => { event.preventDefault(); if (username.trim() && password) onSubmit(mode, username.trim(), password); };
  return <main className="login-page">
    <header className="login-brand"><Brand /></header>
    <section className="login-form-side"><form className="login-card" onSubmit={handleSubmit}>
      <h2>{mode === 'login' ? 'Welcome to AI Council' : 'Create your account'}</h2><p className="login-tagline">{mode === 'login' ? 'A little help. A fresh perspective. A place to think.' : 'One place for everyday chats and deeper discussions.'}</p>
      {allowSignup && <div className="login-tabs"><button type="button" aria-pressed={mode === 'login'} onClick={() => setMode('login')}>Sign in</button><button type="button" aria-pressed={mode === 'register'} onClick={() => setMode('register')}>Create account</button></div>}
      <label>Username<input autoFocus autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} placeholder={mode === 'login' ? 'Your username' : 'Choose a username'} required disabled={busy} /></label>
      <div className="login-field"><label htmlFor="login-password">Password</label><span className="password-field"><input id="login-password" type={showPassword ? 'text' : 'password'} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={password} onChange={(event) => setPassword(event.target.value)} placeholder={mode === 'register' ? 'At least 8 characters' : 'Your password'} required disabled={busy} /><button type="button" aria-label={showPassword ? 'Hide password' : 'Show password'} onClick={() => setShowPassword(!showPassword)}>{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button></span></div>
      {error && <div className="login-error" role="alert">{error}</div>}
      <button type="submit" className="login-submit" disabled={busy || !username.trim() || !password}>{busy ? 'Signing in…' : mode === 'login' ? 'Sign in' : 'Create account'}<ArrowRight size={16} /></button>
      <p className="login-note"><LockKeyhole size={13} /><span>Your conversations belong to your account.<br />Workspace admins can review them.</span></p>
    </form><p className="login-bottom-line">Chat with one model. Think together with a council.</p></section>
  </main>;
}
