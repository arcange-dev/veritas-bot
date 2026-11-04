import { Logo } from "@/components/brand/Logo";
import { useState } from "react";
import { isConfigured } from "@/lib/env";
import { signInWithOtp } from "@/lib/auth";

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <div className="w-full max-w-sm glass rounded-lg p-6">
        <h1 className="text-[16px] font-semibold text-primary"><Logo size={22} /></h1>
        <p className="mt-1 text-[12.5px] text-muted">
          Your AI engineering team. One intelligent workspace.
        </p>

        {!isConfigured ? (
          <p className="mt-4 rounded-sm border border-warn/30 bg-warn/10 p-3 text-[12px] text-warn">
            Supabase is not configured. Set <code className="font-mono">VITE_SUPABASE_URL</code> and{" "}
            <code className="font-mono">VITE_SUPABASE_ANON_KEY</code> to enable sign-in.
          </p>
        ) : sent ? (
          <p className="mt-4 text-[12.5px] text-ok">Check your inbox for a sign-in link.</p>
        ) : (
          <form
            className="mt-5 flex flex-col gap-3"
            onSubmit={async (event) => {
              event.preventDefault();
              setError(null);
              try {
                await signInWithOtp(email);
                setSent(true);
              } catch (cause) {
                setError(cause instanceof Error ? cause.message : "Sign-in failed.");
              }
            }}
          >
            <label htmlFor="email" className="panel-label">Work email</label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="h-9 rounded-sm border border-subtle bg-base px-2 text-[12.5px] text-primary"
            />
            {error ? <p className="text-[12px] text-danger">{error}</p> : null}
            <button type="submit" className="h-9 rounded-sm bg-accent text-[12.5px] font-medium text-white hover:bg-accent-soft">
              Send sign-in link
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
