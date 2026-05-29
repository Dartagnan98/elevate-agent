"use client";

import { ReactNode } from "react";

// Shared auth-page shell + styles, matching the app login: black canvas with an
// animated aurora gradient (ported from cli/web's onboarding-aurora), the
// Elevate wordmark logo, a #1A1A1A graphite card, #8A8A8A primary button, and
// #ECECEC / #A0A0A0 text. Every auth page (login, signup, forgot, reset)
// renders through this so they stay consistent with the app.
export const AUTH_STYLES = `
.el-auth * { box-sizing: border-box; }
.el-auth {
  position: relative; min-height: 100vh; display: flex; align-items: center; justify-content: center;
  padding: 48px 32px; overflow: hidden;
  background:
    radial-gradient(circle at 22% 18%, rgba(217,119,87,0.10) 0%, transparent 42%),
    radial-gradient(circle at 78% 82%, rgba(217,119,87,0.06) 0%, transparent 48%),
    #0A0A0A;
  color: #ECECEC;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
  -webkit-font-smoothing: antialiased;
}
/* Animated black gradient layer behind the card (app "aurora"). */
.el-auth .aurora {
  position: absolute; inset: 0; pointer-events: none; z-index: 0;
  background: linear-gradient(120deg,
    rgba(217,119,87,0.08) 0%, transparent 35%,
    rgba(217,119,87,0.05) 70%, transparent 100%);
  background-size: 220% 220%;
  animation: el-aurora 9s ease-in-out infinite;
}
@keyframes el-aurora { 0%,100% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } }
@keyframes el-rise { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }
.el-auth .card {
  position: relative; z-index: 1; width: 400px; max-width: 100%;
  background: #1A1A1A; border: 1px solid #2A2A2A; border-radius: 12px; padding: 32px 28px;
  box-shadow: 0 24px 60px rgba(0,0,0,0.45);
  animation: el-rise 520ms cubic-bezier(0.22, 1, 0.36, 1) both;
}
.el-auth .brand { display: flex; align-items: center; margin: 0 0 18px; }
.el-auth .brand img { height: 22px; width: auto; object-fit: contain; }
.el-auth h1 { margin: 0 0 6px; font-size: 20px; font-weight: 600; letter-spacing: -0.01em; }
.el-auth .subtitle { margin: 0 0 24px; font-size: 13px; color: #A0A0A0; line-height: 1.4; }
.el-auth form { display: flex; flex-direction: column; gap: 12px; }
.el-auth label { font-size: 12px; color: #A0A0A0; margin-bottom: -8px; }
.el-auth input[type=email], .el-auth input[type=password], .el-auth input[type=text] {
  background: #0F0F0F; border: 1px solid #2A2A2A; border-radius: 6px; color: #ECECEC;
  padding: 10px 12px; font-size: 14px; font-family: inherit; outline: none; transition: border-color 0.15s; width: 100%;
}
.el-auth input:focus { border-color: #B0B0B0; }
.el-auth input.code { letter-spacing: 0.3em; font-size: 18px; text-align: center; }
.el-auth button.primary {
  background: #8A8A8A; color: #0F0F0F; border: 0; border-radius: 6px; padding: 11px 14px;
  font-size: 14px; font-weight: 600; cursor: pointer; margin-top: 6px; font-family: inherit; transition: background 0.15s; width: 100%;
}
.el-auth button.primary:hover:not(:disabled) { background: #B0B0B0; }
.el-auth button.primary:disabled { opacity: 0.6; cursor: not-allowed; }
.el-auth button.sm { width: auto; margin-top: 0; padding: 7px 12px; font-size: 13px; }
.el-auth button.ghost { background: transparent; color: #ECECEC; border: 1px solid #2A2A2A; }
.el-auth button.ghost:hover:not(:disabled) { background: #222; }
.el-auth .row-links { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-top: 14px; font-size: 12px; flex-wrap: wrap; }
.el-auth a, .el-auth .linkbtn { color: #B0B0B0; text-decoration: none; cursor: pointer; background: none; border: 0; font-size: 12px; font-family: inherit; padding: 0; }
.el-auth a:hover, .el-auth .linkbtn:hover { text-decoration: underline; }
.el-auth .status { min-height: 18px; font-size: 12px; margin-top: 8px; line-height: 1.4; }
.el-auth .status.error { color: #E07570; }
.el-auth .status.info { color: #A0A0A0; }
.el-auth .divider { border-top: 1px solid #2A2A2A; margin: 20px 0 16px; }
.el-auth .footer { font-size: 13px; color: #A0A0A0; text-align: center; }
.el-auth .footer a, .el-auth .footer .linkbtn { font-size: 13px; }
.el-auth .alt-action { font-size: 12px; color: #A0A0A0; text-align: center; }
.el-auth .notice { padding: 14px 16px; background: #0F0F0F; border: 1px solid #2A2A2A; border-radius: 8px; color: #ECECEC; font-size: 13px; line-height: 1.45; }
.el-auth .devbox { margin-top: 14px; padding: 14px 16px; background: #0F0F0F; border: 1px dashed #2A2A2A; border-radius: 8px; }
.el-auth .devbox .lbl { font-size: 10px; color: #A0A0A0; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px; font-family: monospace; }
.el-auth .devbox .url { font-size: 12px; font-family: monospace; color: #ECECEC; word-break: break-all; margin-bottom: 10px; }
.el-auth .devbox .actions { display: flex; gap: 8px; }
`;

export function AuthShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <div className="el-auth">
      <style dangerouslySetInnerHTML={{ __html: AUTH_STYLES }} />
      <div className="aurora" aria-hidden />
      <div className="card">
        <div className="brand">
          <img src="/elevateos-wordmark-dark.png" alt="Elevate" />
        </div>
        <h1>{title}</h1>
        <p className="subtitle">{subtitle}</p>
        {children}
      </div>
    </div>
  );
}
