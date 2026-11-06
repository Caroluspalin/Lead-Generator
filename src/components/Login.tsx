import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { LogIn, UserPlus, Loader2, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import { useAuth } from '../context/AuthContext';

const Login: React.FC = () => {
  const { signIn, signUp } = useAuth();
  const [mode, setMode] = useState<'signin' | 'signup'>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) {
      setError('Enter email and password');
      return;
    }
    setLoading(true);
    setError('');
    try {
      if (mode === 'signin') {
        await signIn(email, password);
        toast.success('Welcome back');
      } else {
        await signUp(email, password);
        toast.success('Account created — check your email to confirm');
      }
    } catch (err) {
      const msg = (err as Error).message || 'Authentication failed';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const inputClass =
    'w-full h-control text-sm bg-canvas border border-line-strong rounded px-3 text-fg transition-colors';

  return (
    <div className="min-h-screen flex items-center justify-center bg-canvas px-4">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="w-full max-w-sm"
      >
        <div className="mb-6 flex flex-col items-center text-center">
          <div className="mb-4 grid size-9 place-content-center rounded bg-accent">
            <svg width="20" viewBox="0 0 50 39" fill="none" xmlns="http://www.w3.org/2000/svg" className="fill-accent-fg" aria-hidden="true">
              <path d="M16.4992 2H37.5808L22.0816 24.9729H1L16.4992 2Z" />
              <path d="M17.4224 27.102L11.4192 36H33.5008L49 13.0271H32.7024L23.2064 27.102H17.4224Z" />
            </svg>
          </div>
          <h1 className="text-xl font-semibold tracking-tight text-fg">Agency Hunter</h1>
          <p className="text-sm text-fg-subtle mt-1">
            {mode === 'signin' ? 'Sign in to continue' : 'Create an account'}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3.5 bg-surface border border-line rounded-lg p-5">
          <div>
            <label htmlFor="login-email" className="block text-2xs font-medium text-fg-muted mb-1.5">
              Email
            </label>
            <input
              id="login-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              className={inputClass}
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label htmlFor="login-password" className="block text-2xs font-medium text-fg-muted mb-1.5">
              Password
            </label>
            <input
              id="login-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
              className={inputClass}
              placeholder="••••••••"
            />
          </div>

          {error && (
            <div role="alert" className="px-3 py-2 bg-danger/10 text-fg text-sm rounded border border-danger/30 flex items-start gap-2">
              <AlertTriangle size={14} className="shrink-0 mt-[3px] text-danger" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full inline-flex items-center justify-center gap-2 h-control px-4 text-sm font-medium text-accent-fg bg-accent hover:bg-accent-hover disabled:opacity-60 disabled:cursor-not-allowed rounded transition-colors"
          >
            {loading ? (
              <Loader2 size={14} className="animate-spin" />
            ) : mode === 'signin' ? (
              <LogIn size={14} />
            ) : (
              <UserPlus size={14} />
            )}
            {mode === 'signin' ? 'Sign in' : 'Create account'}
          </button>
        </form>

        <div className="mt-4 text-center">
          <button
            type="button"
            onClick={() => {
              setMode(mode === 'signin' ? 'signup' : 'signin');
              setError('');
            }}
            className="rounded-sm text-xs text-fg-muted hover:text-fg underline decoration-fg-subtle/40 underline-offset-2 hover:decoration-fg transition-colors"
          >
            {mode === 'signin'
              ? "Don't have an account? Sign up"
              : 'Already have an account? Sign in'}
          </button>
        </div>
      </motion.div>
    </div>
  );
};

export default Login;
