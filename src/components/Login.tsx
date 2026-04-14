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

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 via-indigo-50 to-purple-50 px-4">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="w-full max-w-md bg-white rounded-2xl shadow-xl border border-slate-200 p-8"
      >
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-slate-900">Agency Hunter</h1>
          <p className="text-sm text-slate-500 mt-1">
            {mode === 'signin' ? 'Sign in to continue' : 'Create an account'}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide mb-1.5">
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              className="w-full text-sm border-2 border-slate-200 rounded-lg px-4 py-2.5 text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 transition-colors"
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide mb-1.5">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
              className="w-full text-sm border-2 border-slate-200 rounded-lg px-4 py-2.5 text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500 transition-colors"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <div className="p-3 bg-red-50 text-red-700 text-sm rounded-lg border border-red-100 flex items-start gap-2">
              <AlertTriangle size={16} className="shrink-0 mt-0.5 text-red-500" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed rounded-lg shadow-sm shadow-indigo-200 transition-colors"
          >
            {loading ? (
              <Loader2 size={16} className="animate-spin" />
            ) : mode === 'signin' ? (
              <LogIn size={16} />
            ) : (
              <UserPlus size={16} />
            )}
            {mode === 'signin' ? 'Sign in' : 'Create account'}
          </button>
        </form>

        <div className="mt-6 text-center">
          <button
            type="button"
            onClick={() => {
              setMode(mode === 'signin' ? 'signup' : 'signin');
              setError('');
            }}
            className="text-xs text-slate-500 hover:text-indigo-600 transition-colors"
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
