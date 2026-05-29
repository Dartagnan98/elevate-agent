"use client";

import { ReactNode } from "react";

// Shared auth-page shell + styles, matching the Electron desktop login
// (desktop/src/login.html): #0F0F0F canvas, #1A1A1A card, #2A2A2A borders,
// #8A8A8A brand-dot + primary button, #ECECEC / #A0A0A0 text, SF Pro stack.
// Every auth page (login, signup, forgot, reset) renders through this so they
// stay pixel-consistent with the app.
export const AUTH_STYLES = `
.el-auth * { box-sizing: border-box; }
.el-auth {
  min-height: 100vh; display: flex; align-items: center; justify-content: center;
  padding: 48px 32px; background: #0F0F0F; color: #ECECEC;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
  -webkit-font-smoothing: antialiased;
}
.el-auth .card { width: 400px; max-width: 100%; background: #1A1A1A; border: 1px solid #2A2A2A; border-radius: 12px; padding: 32px 28px; }
.el-auth .brand { display: flex; align-items: center; gap: 10px; margin: 0 0 16px; }
.el-auth .brand-dot { width: 10px; height: 10px; border-radius: 3px; background: #8A8A8A; }
.el-auth .brand-name { font-size: 16px; font-weight: 600; letter-spacing: -0.01em; }
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
      <div className="card">
        <div className="brand">
          <div className="brand-dot" />
          <div className="brand-name">Elevate</div>
        </div>
        <h1>{title}</h1>
        <p className="subtitle">{subtitle}</p>
        {children}
      </div>
    </div>
  );
}
