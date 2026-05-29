"use client";

import { AuthShell } from "@/components/auth-shell";

// Elevate is invite-only — there is no public sign-up. Accounts are created by
// accepting an admin invitation. This page exists only to explain that to
// anyone who lands on /signup from an old link or bookmark.
export default function SignupPage() {
  return (
    <AuthShell title="Invite-only access" subtitle="Elevate accounts are created by invitation.">
      <div className="notice">
        There's no public sign-up. If you've been invited, open the invitation
        link from your email to set up your account. Otherwise, ask your Elevate
        admin to send you an invite.
      </div>

      <div className="divider" />
      <div className="footer">
        <a href="/admin/login">Back to sign in</a>
      </div>
    </AuthShell>
  );
}
