"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

type Mode = "password" | "code";

// Styles mirror the Electron desktop login (desktop/src/login.html) exactly so
// the web sign-in matches the app: #0F0F0F canvas, #1A1A1A card, #2A2A2A
// borders, #8A8A8A primary button, #ECECEC / #A0A0A0 text.
const STYLES = `
.el-login * { box-sizing: border-box; }
.el-login {
  min-height: 100vh;
  display: flex; align-items: center; justify-content: center;
  padding: 48px 32px;
  background: #0F0F0F; color: #ECECEC;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
  -webkit-font-smoothing: antialiased;
}
.el-login .card {
  width: 380px; background: #1A1A1A; border: 1px solid #2A2A2A;
  border-radius: 12px; padding: 32px 28px;
}
.el-login .brand { display: flex; align-items: center; gap: 10px; margin: 0 0 4px; }
.el-login .brand-dot { width: 10px; height: 10px; border-radius: 3px; background: #8A8A8A; }
.el-login .brand-name { font-size: 16px; font-weight: 600; letter-spacing: -0.01em; }
.el-login h1 { margin: 16px 0 6px; font-size: 20px; font-weight: 600; letter-spacing: -0.01em; }
.el-login .subtitle { margin: 0 0 24px; font-size: 13px; color: #A0A0A0; line-height: 1.4; }
.el-login form { display: flex; flex-direction: column; gap: 12px; }
.el-login label { font-size: 12px; color: #A0A0A0; margin-bottom: -8px; }
.el-login input[type=email], .el-login input[type=password], .el-login input[type=text] {
  background: #0F0F0F; border: 1px solid #2A2A2A; border-radius: 6px; color: #ECECEC;
  padding: 10px 12px; font-size: 14px; font-family: inherit; outline: none; transition: border-color 0.15s;
}
.el-login input:focus { border-color: #B0B0B0; }
.el-login input.code { letter-spacing: 0.3em; font-size: 18px; text-align: center; }
.el-login button.primary {
  background: #8A8A8A; color: #0F0F0F; border: 0; border-radius: 6px; padding: 11px 14px;
  font-size: 14px; font-weight: 600; cursor: pointer; margin-top: 6px; font-family: inherit; transition: background 0.15s;
}
.el-login button.primary:hover:not(:disabled) { background: #B0B0B0; }
.el-login button.primary:disabled { opacity: 0.6; cursor: not-allowed; }
.el-login .row-links { display: flex; justify-content: space-between; margin-top: 14px; font-size: 12px; }
.el-login a, .el-login .linkbtn {
  color: #B0B0B0; text-decoration: none; cursor: pointer; background: none; border: 0;
  font-size: 12px; font-family: inherit; padding: 0;
}
.el-login a:hover, .el-login .linkbtn:hover { text-decoration: underline; }
.el-login .status { min-height: 18px; font-size: 12px; margin-top: 8px; line-height: 1.4; }
.el-login .status.error { color: #E07570; }
.el-login .status.info { color: #A0A0A0; }
.el-login .divider { border-top: 1px solid #2A2A2A; margin: 20px 0 16px; }
.el-login .alt-action { font-size: 12px; color: #A0A0A0; text-align: center; }
`;

function LoginInner() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/admin/users";

  const [mode, setMode] = useState<Mode>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [codeSent, setCodeSent] = useState(false);
  const [status, setStatus] = useState<{ text: string; kind: "error" | "info" } | null>(null);
  const [loading, setLoading] = useState(false);

  function finishLogin(data: { access_token: string; refresh_token: string }) {
    localStorage.setItem("elevate_access", data.access_token);
    localStorage.setItem("elevate_refresh", data.refresh_token);
    const safeNext = next.startsWith("/") && !next.startsWith("//") ? next : "/admin/users";
    router.push(safeNext);
  }

  function switchMode(m: Mode) {
    setMode(m);
    setStatus(null);
    setCode("");
    setCodeSent(false);
  }

  async function submitPassword(e: React.FormEvent) {
    e.preventDefault();
    setStatus({ text: "Signing in...", kind: "info" });
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, password, device_label: "web" }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not sign in.");
      setStatus({ text: "Welcome back. Loading...", kind: "info" });
      finishLogin(data);
    } catch (e: unknown) {
      setStatus({ text: e instanceof Error ? e.message : "Could not sign in.", kind: "error" });
      setLoading(false);
    }
  }

  async function requestCode(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setStatus({ text: "Sending code...", kind: "info" });
    try {
      const res = await fetch("/api/auth/login-code/request", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not send code.");
      setCodeSent(true);
      setStatus({ text: "If that email has an account, a 6-digit code is on its way (expires in 10 min).", kind: "info" });
    } catch (e: unknown) {
      setStatus({ text: e instanceof Error ? e.message : "Could not send code.", kind: "error" });
    } finally {
      setLoading(false);
    }
  }

  async function verifyCode(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setStatus({ text: "Verifying...", kind: "info" });
    try {
      const res = await fetch("/api/auth/login-code/verify", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, code, device_label: "web" }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Invalid code.");
      setStatus({ text: "Welcome back. Loading...", kind: "info" });
      finishLogin(data);
    } catch (e: unknown) {
      setStatus({ text: e instanceof Error ? e.message : "Invalid code.", kind: "error" });
      setLoading(false);
    }
  }

  const subtitle =
    mode === "password"
      ? "Use your Elevation Real Estate HQ account."
      : codeSent
        ? "Enter the 6-digit code we emailed you."
        : "We'll email you a one-time sign-in code.";

  const signupHref = `/signup${next !== "/admin/users" ? `?next=${encodeURIComponent(next)}` : ""}`;

  return (
    <div className="el-login">
      <style dangerouslySetInnerHTML={{ __html: STYLES }} />
      <div className="card">
        <div className="brand">
          <div className="brand-dot" />
          <div className="brand-name">Elevate</div>
        </div>
        <h1>Sign in</h1>
        <p className="subtitle">{subtitle}</p>

        {mode === "password" && (
          <form onSubmit={submitPassword}>
            <label htmlFor="email">Email</label>
            <input id="email" type="email" autoComplete="email" autoFocus required
              value={email} onChange={(e) => setEmail(e.target.value)} />
            <label htmlFor="password">Password</label>
            <input id="password" type="password" autoComplete="current-password" required
              value={password} onChange={(e) => setPassword(e.target.value)} />
            <button className="primary" type="submit" disabled={loading}>
              {loading ? "Signing in..." : "Sign in"}
            </button>
            {status && <div className={`status ${status.kind}`}>{status.text}</div>}
          </form>
        )}

        {mode === "code" && !codeSent && (
          <form onSubmit={requestCode}>
            <label htmlFor="email">Email</label>
            <input id="email" type="email" autoComplete="email" autoFocus required
              value={email} onChange={(e) => setEmail(e.target.value)} />
            <button className="primary" type="submit" disabled={loading}>
              {loading ? "Sending code..." : "Email me a code"}
            </button>
            {status && <div className={`status ${status.kind}`}>{status.text}</div>}
          </form>
        )}

        {mode === "code" && codeSent && (
          <form onSubmit={verifyCode}>
            <label htmlFor="code">6-digit code</label>
            <input id="code" type="text" inputMode="numeric" autoComplete="one-time-code"
              className="code" maxLength={6} placeholder="123456" autoFocus required
              value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} />
            <button className="primary" type="submit" disabled={loading}>
              {loading ? "Verifying..." : "Verify & sign in"}
            </button>
            {status && <div className={`status ${status.kind}`}>{status.text}</div>}
            <div className="alt-action" style={{ marginTop: 10 }}>
              <button type="button" className="linkbtn" onClick={() => { setCodeSent(false); setCode(""); setStatus(null); }}>
                Use a different email or resend
              </button>
            </div>
          </form>
        )}

        <div className="row-links">
          {mode === "password" ? (
            <>
              <a href="/forgot">Forgot password?</a>
              <a href={signupHref}>Create account</a>
            </>
          ) : (
            <a href={signupHref}>Create account</a>
          )}
        </div>

        <div className="divider" />
        <div className="alt-action">
          <button type="button" className="linkbtn" onClick={() => switchMode(mode === "password" ? "code" : "password")}>
            {mode === "password" ? "Sign in with a code instead" : "Use password instead"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AdminLogin() {
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  );
}
