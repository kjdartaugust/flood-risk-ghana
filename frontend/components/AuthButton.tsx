"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth";

export default function AuthButton() {
  const { session, loading, configured, signIn, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Nothing to offer if this deployment has no Supabase project behind it.
  if (!configured || loading) return null;

  if (session) {
    return (
      <div className="auth">
        <span className="muted auth-email">{session.user.email}</span>
        <button className="btn ghost sm" onClick={() => signOut()}>
          Sign out
        </button>
      </div>
    );
  }

  async function send(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await signIn(email.trim());
      setSent(true);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="auth">
      {!open ? (
        <button className="btn ghost sm" onClick={() => setOpen(true)}>
          Sign in
        </button>
      ) : sent ? (
        <span className="muted">Check {email} for a sign-in link.</span>
      ) : (
        <form className="auth-form" onSubmit={send}>
          <input
            type="email"
            required
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-label="Email address"
          />
          <button className="btn sm" type="submit">
            Send link
          </button>
        </form>
      )}
      {error && <span className="err">{error}</span>}
    </div>
  );
}
