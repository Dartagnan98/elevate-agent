import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Loader2, LogOut, Package } from "lucide-react";
import { api } from "@/lib/api";
import { useTheme } from "@/themes/context";
import type {
  LicenseStatusResponse,
  LicenseActivateResponse,
} from "@/lib/api-types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

type Phase =
  | "loading"
  | "logged_out"
  | "signing_in"
  | "syncing"
  | "success"
  | "authenticated"
  | "error";

interface Props {
  onAuthChange?: (authenticated: boolean, packs?: LicenseStatusResponse["packs"]) => void;
}

type ActivationOutcomeHandlers = {
  confirmed: (result: LicenseActivateResponse) => void;
  incomplete: (message: string, result: LicenseActivateResponse) => void;
};

function activationIncompleteMessage(result: LicenseActivateResponse): string {
  const warning = Array.isArray(result.skill_sync_warnings)
    ? result.skill_sync_warnings.find((item) => typeof item === "string" && item.trim())
    : undefined;
  const detail = result.skill_error?.trim() || warning?.trim();
  const prefix =
    "Your account was verified, but Elevate could not finish this device's required setup. " +
    "Workspace access was not granted.";
  return detail ? `${prefix} ${detail} Try again.` : `${prefix} Try again.`;
}

function requiredSetupMessage(status?: LicenseStatusResponse | null): string {
  const detail = status?.status_text?.trim();
  return detail || "Your account is verified. Finish required Realtor Beta setup to open the workspace.";
}

// Keep polling/focus changes fail-closed when HQ credentials were accepted but
// the device has not durably completed its required signed-skill setup.
// eslint-disable-next-line react-refresh/only-export-components
export function needsRequiredSetup(status: LicenseStatusResponse): boolean {
  return status.account_verified === true && status.activation_complete !== true;
}

/**
 * Keep the security-sensitive activation decision independently testable.
 * Older or partial server responses must never fall through to the success path.
 */
// This export is a narrow test seam for the fail-closed activation boundary.
// eslint-disable-next-line react-refresh/only-export-components
export function applyActivationOutcome(
  result: LicenseActivateResponse,
  handlers: ActivationOutcomeHandlers,
): boolean {
  if (result.authenticated !== true || result.activation_complete !== true) {
    handlers.incomplete(activationIncompleteMessage(result), result);
    return false;
  }
  handlers.confirmed(result);
  return true;
}

export function LoginCard({ onAuthChange }: Props) {
  const { themeName } = useTheme();
  const logoSrc =
    themeName === "light" ? "/elevateos-wordmark.png" : "/elevateos-wordmark-dark.png";
  const [phase, setPhase] = useState<Phase>("loading");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [licenseStatus, setLicenseStatus] = useState<LicenseStatusResponse | null>(null);
  const [activationResult, setActivationResult] = useState<LicenseActivateResponse | null>(null);
  const [mode, setMode] = useState<"password" | "code" | "create">("password");
  const [code, setCode] = useState("");
  const [codeSent, setCodeSent] = useState(false);
  const [requestingCode, setRequestingCode] = useState(false);
  const incompleteActivation = useRef(false);

  const loadStatus = useCallback(async () => {
    try {
      const status = await api.getLicenseStatus();
      setLicenseStatus(status);
      if (needsRequiredSetup(status)) {
        incompleteActivation.current = true;
        setError(requiredSetupMessage(status));
        setPhase("error");
        onAuthChange?.(false, status.packs);
        return;
      }
      if (status.authenticated) {
        incompleteActivation.current = false;
        setError(null);
        setPhase("authenticated");
        onAuthChange?.(true, status.packs);
      } else {
        setPhase("logged_out");
        onAuthChange?.(false, status.packs);
      }
    } catch {
      if (!incompleteActivation.current) setPhase("logged_out");
    }
  }, [onAuthChange]);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  // Self-heal: if the desktop main process refreshes the license (admin
  // revokes a pack on HQ, sign-out from another tab, etc.) or the window
  // regains focus, re-fetch status so the form/card flips without a reload.
  useEffect(() => {
    const handler = () => loadStatus();
    const onVisibility = () => {
      if (document.visibilityState === "visible") handler();
    };
    window.addEventListener("elevate:auth-changed", handler);
    window.addEventListener("focus", handler);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("elevate:auth-changed", handler);
      window.removeEventListener("focus", handler);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [loadStatus]);

  // Shared confirmation boundary for password, code, and account creation.
  // Required setup runs inline. A partial response stays logged out and can be
  // retried by the user; it is never converted into success by a background job.
  const completeActivation = async (result: LicenseActivateResponse) => {
    const confirmed = applyActivationOutcome(result, {
      confirmed: (confirmedResult) => {
        incompleteActivation.current = false;
        setActivationResult(confirmedResult);
        setError(null);
        setPhase("success");
        onAuthChange?.(true, confirmedResult.packs);
      },
      incomplete: (message, incompleteResult) => {
        incompleteActivation.current = true;
        setActivationResult(null);
        setLicenseStatus(null);
        setPhase("error");
        setError(message);
        onAuthChange?.(false, incompleteResult.packs);

        // Account creation can be retried as a normal sign-in. A consumed or
        // expired one-time code must be requested again instead of replayed.
        if (mode === "create") setMode("password");
        if (mode === "code") {
          setCode("");
          setCodeSent(false);
        }
      },
    });
    if (!confirmed) return;

    window.dispatchEvent(new Event("elevate:auth-changed"));
    await loadStatus();
  };

  const showAuthError = async (err: unknown, invalidMsg: string) => {
    setPhase("error");
    const message = err instanceof Error ? err.message : String(err);
    if (message.includes("401") || message.includes("Invalid")) {
      setError(invalidMsg);
    } else if (message.includes("402")) {
      setError("No active subscription. Contact Elevation Real Estate HQ.");
    } else {
      setError(message);
    }
    try {
      const status = await api.getLicenseStatus();
      if (needsRequiredSetup(status)) {
        incompleteActivation.current = true;
        setLicenseStatus(status);
        setError(requiredSetupMessage(status));
        setPhase("error");
        onAuthChange?.(false, status.packs);
      }
    } catch {
      // Preserve the original actionable authentication error.
    }
  };

  const openForgot = () => {
    // Desktop maps the relative target ("forgot") to HQ_BASE_URL and opens it
    // in the system browser; web falls back to window.open.
    const ext = (window as unknown as { elevateDesktop?: { auth?: { openExternal?: (t: string) => void } } })
      .elevateDesktop?.auth?.openExternal;
    if (ext) ext("forgot");
    else window.open("https://api.elevationrealestatehq.com/forgot", "_blank", "noopener");
  };

  const handleSignIn = async () => {
    if (!email.trim() || !password) return;
    incompleteActivation.current = true;
    setPhase("signing_in");
    setError(null);
    try {
      const result = await api.activateLicense(email.trim(), password);
      await completeActivation(result);
    } catch (err: unknown) {
      await showAuthError(err, "Invalid email or password.");
    }
  };

  const handleCreateAccount = async () => {
    if (!firstName.trim() || !lastName.trim()) {
      setPhase("error");
      setError("Enter your first and last name.");
      return;
    }
    if (!email.trim() || !password) return;
    if (password.length < 8) {
      setPhase("error");
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setPhase("error");
      setError("Passwords don't match.");
      return;
    }
    incompleteActivation.current = true;
    setPhase("signing_in");
    setError(null);
    try {
      const result = await api.createAccount(
        email.trim(),
        password,
        firstName.trim(),
        lastName.trim(),
      );
      await completeActivation(result);
    } catch (err: unknown) {
      await showAuthError(err, "Could not create the account.");
    }
  };

  const switchMode = (next: "password" | "code" | "create") => {
    setMode(next);
    setError(null);
    setCodeSent(false);
    setCode("");
    setPassword("");
    setConfirmPassword("");
    setFirstName("");
    setLastName("");
    if (phase === "error") setPhase("logged_out");
  };

  const handleRequestCode = async () => {
    if (!email.trim()) return;
    setError(null);
    setRequestingCode(true);
    try {
      await api.requestLoginCode(email.trim());
      setCodeSent(true);
    } catch (err: unknown) {
      // fetchJSON throws "<status>: <body>" — surface the real reason instead
      // of a blanket message so failures are diagnosable.
      const raw = err instanceof Error ? err.message : String(err);
      const m = raw.match(/^(\d{3}):\s*([\s\S]*)$/);
      let msg = "Could not send the code. Check the email and try again.";
      if (m) {
        if (m[1] === "429") {
          msg = "Too many code requests. Wait a few minutes and try again.";
        } else {
          try {
            const body = JSON.parse(m[2]);
            msg = body.detail || body.error || `Couldn't send code (error ${m[1]}).`;
          } catch {
            msg = `Couldn't send code (error ${m[1]}).`;
          }
        }
      } else if (raw) {
        msg = raw;
      }
      setError(msg);
    } finally {
      setRequestingCode(false);
    }
  };

  const handleVerifyCode = async () => {
    if (!email.trim() || !code.trim()) return;
    incompleteActivation.current = true;
    setPhase("signing_in");
    setError(null);
    try {
      const result = await api.activateWithCode(email.trim(), code.trim());
      await completeActivation(result);
    } catch (err: unknown) {
      await showAuthError(err, "Invalid or expired code.");
    }
  };

  const handleLogout = async () => {
    try {
      const result = await api.logoutLicense();
      incompleteActivation.current = false;
      setLicenseStatus(null);
      setActivationResult(null);
      setPhase("logged_out");
      setEmail("");
      setPassword("");
      setMode("password");
      setCode("");
      setCodeSent(false);
      onAuthChange?.(false, result.packs);
      window.dispatchEvent(new Event("elevate:auth-changed"));
    } catch (err: unknown) {
      setPhase("error");
      const detail = err instanceof Error ? err.message : String(err);
      setError(detail || "Elevate could not clear the pending sign-in. Try again.");
      onAuthChange?.(false, licenseStatus?.packs);
    }
  };

  const handleRetryRequiredSetup = async () => {
    incompleteActivation.current = true;
    setPhase("syncing");
    setError(null);
    onAuthChange?.(false, licenseStatus?.packs);
    try {
      const result = await api.syncLicenseSkills();
      if (result.activation_complete !== true || result.errors.length > 0) {
        const detail = result.errors.find((item) => item.trim());
        throw new Error(
          detail || "Elevate could not verify every required Realtor Beta skill.",
        );
      }
      incompleteActivation.current = false;
      setLicenseStatus((current) => current
        ? {
            ...current,
            authenticated: true,
            activation_complete: true,
            packs: result.packs,
            status_text: "Required Realtor Beta setup complete.",
          }
        : current);
      setError(null);
      setPhase("authenticated");
      onAuthChange?.(true, result.packs);
      window.dispatchEvent(new Event("elevate:auth-changed"));
      await loadStatus();
    } catch (err: unknown) {
      const detail = err instanceof Error ? err.message : String(err);
      setError(
        detail || "Elevate could not finish required Realtor Beta setup. Try again.",
      );
      setPhase("error");
      onAuthChange?.(false, licenseStatus?.packs);
    }
  };

  if (phase === "loading") {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (licenseStatus && needsRequiredSetup(licenseStatus)) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Finish Realtor Beta setup</CardTitle>
          <CardDescription>
            Account verified as {licenseStatus.email}. Workspace access stays locked until required skills finish installing.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {error && (
            <p className="rounded-sm border border-border bg-card px-3 py-2 text-xs font-medium text-destructive">
              {error}
            </p>
          )}
          <Button
            type="button"
            className="w-full"
            onClick={handleRetryRequiredSetup}
            disabled={phase === "syncing"}
          >
            {phase === "syncing" ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Installing required skills...
              </>
            ) : (
              "Retry required setup"
            )}
          </Button>
          <Button
            type="button"
            variant="ghost"
            className="w-full text-muted-foreground"
            onClick={handleLogout}
            disabled={phase === "syncing"}
          >
            <LogOut className="h-3.5 w-3.5" />
            Sign out and start over
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (phase === "authenticated" && licenseStatus) {
    const enabledPacks = Object.entries(licenseStatus.packs)
      .filter(([key, val]) => val && key !== "realEstateAny")
      .map(([key]) => {
        const labels: Record<string, string> = {
          realEstateSales: "Leads",
          realEstateMarketing: "Social & Marketing",
          realEstateAdmin: "Admin",
          realEstateCma: "CMA",
        };
        return labels[key] ?? key;
      });

    return (
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Elevation HQ</CardTitle>
              <CardDescription>Signed in as {licenseStatus.email}</CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1 rounded bg-[var(--color-success)]/10 px-2.5 py-1 font-mono-ui text-[0.66rem] font-semibold uppercase tracking-[0.06em] text-[var(--color-success)]">
                <Check className="h-3 w-3" />
                Active
              </span>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Tier</span>
            <span className="font-medium capitalize">{licenseStatus.tier}</span>
          </div>
          {enabledPacks.length > 0 && (
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Skill Packs</span>
              <div className="flex flex-wrap justify-end gap-1">
                {enabledPacks.map((pack) => (
                  <span
                    key={pack}
                    className="inline-flex items-center gap-1 rounded-sm border border-border bg-card px-2 py-0.5 text-[0.72rem] font-medium text-primary"
                  >
                    <Package className="h-3 w-3" />
                    {pack}
                  </span>
                ))}
              </div>
            </div>
          )}
          <div className="pt-2">
            <Button variant="ghost" size="sm" onClick={handleLogout} className="text-muted-foreground">
              <LogOut className="h-3.5 w-3.5" />
              Sign out
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (phase === "success" && activationResult) {
    const packs = activationResult.packs;
    const enabledPacks = Object.entries(packs)
      .filter(([key, val]) => val && key !== "realEstateAny")
      .map(([key]) => {
        const labels: Record<string, string> = {
          realEstateSales: "Leads",
          realEstateMarketing: "Social & Marketing",
          realEstateAdmin: "Admin",
          realEstateCma: "CMA",
        };
        return labels[key] ?? key;
      });

    return (
      <Card>
        <CardHeader>
          <CardTitle>Welcome to Elevation</CardTitle>
          <CardDescription>Signed in as {activationResult.email}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {enabledPacks.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground">Unlocked Skill Packs</p>
              <div className="grid gap-2">
                {enabledPacks.map((pack) => (
                  <div
                    key={pack}
                    className="flex items-center gap-2.5 rounded-md border border-[var(--color-success)]/20 bg-[var(--color-success)]/5 px-3 py-2"
                  >
                    <Check className="h-4 w-4 text-[var(--color-success)]" />
                    <span className="text-sm font-medium">{pack}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {activationResult.skill_count > 0 && (
            <p className="text-xs text-muted-foreground">
              {activationResult.skill_count} skills synced
            </p>
          )}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="items-center text-center">
        <div className="flex h-8 items-center justify-center">
          <img
            src={logoSrc}
            alt="Elevation"
            className="h-7 w-auto object-contain"
            draggable={false}
          />
        </div>
        <CardDescription className="pt-1">
          {mode === "create"
            ? "Create your Elevation account. You'll set up your profile right after."
            : "Enter your Elevation Real Estate HQ credentials to unlock your skill packs."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (mode === "create") handleCreateAccount();
            else if (mode === "password") handleSignIn();
            else if (!codeSent) handleRequestCode();
            else handleVerifyCode();
          }}
          className="space-y-3"
        >
          {mode === "create" && (
            <div className="flex gap-2">
              <div className="flex-1 space-y-1.5">
                <label htmlFor="login-firstname" className="text-xs font-medium text-muted-foreground">
                  First name
                </label>
                <Input
                  id="login-firstname"
                  type="text"
                  placeholder="First"
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                  disabled={phase === "signing_in" || phase === "syncing"}
                  autoComplete="given-name"
                />
              </div>
              <div className="flex-1 space-y-1.5">
                <label htmlFor="login-lastname" className="text-xs font-medium text-muted-foreground">
                  Last name
                </label>
                <Input
                  id="login-lastname"
                  type="text"
                  placeholder="Last"
                  value={lastName}
                  onChange={(e) => setLastName(e.target.value)}
                  disabled={phase === "signing_in" || phase === "syncing"}
                  autoComplete="family-name"
                />
              </div>
            </div>
          )}

          <div className="space-y-1.5">
            <label htmlFor="login-email" className="text-xs font-medium text-muted-foreground">
              Email
            </label>
            <Input
              id="login-email"
              type="email"
              placeholder="you@elevationrealestatehq.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={phase === "signing_in" || phase === "syncing" || codeSent}
              autoComplete="email"
              autoFocus
            />
          </div>

          {(mode === "password" || mode === "create") && (
            <div className="space-y-1.5">
              <label htmlFor="login-password" className="text-xs font-medium text-muted-foreground">
                Password
              </label>
              <Input
                id="login-password"
                type="password"
                placeholder={mode === "create" ? "Create a password (8+ characters)" : "Password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={phase === "signing_in" || phase === "syncing"}
                autoComplete={mode === "create" ? "new-password" : "current-password"}
              />
            </div>
          )}

          {mode === "create" && (
            <div className="space-y-1.5">
              <label htmlFor="login-confirm" className="text-xs font-medium text-muted-foreground">
                Confirm password
              </label>
              <Input
                id="login-confirm"
                type="password"
                placeholder="Re-enter password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                disabled={phase === "signing_in" || phase === "syncing"}
                autoComplete="new-password"
              />
            </div>
          )}

          {mode === "code" && codeSent && (
            <div className="space-y-1.5">
              <label htmlFor="login-code" className="text-xs font-medium text-muted-foreground">
                6-digit code
              </label>
              <Input
                id="login-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="123456"
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                disabled={phase === "signing_in" || phase === "syncing"}
                autoFocus
              />
              <p className="text-[0.72rem] text-muted-foreground/70">
                We emailed a code to {email.trim()}.{" "}
                <button
                  type="button"
                  onClick={handleRequestCode}
                  disabled={requestingCode}
                  className="underline underline-offset-2 hover:text-muted-foreground"
                >
                  Resend
                </button>
              </p>
            </div>
          )}

          {error && (
            <div className="space-y-2">
              <p className="rounded-sm border border-border bg-card px-3 py-2 text-xs font-medium text-destructive">
                {error}
              </p>
              {phase === "error" && (
                <button
                  type="button"
                  onClick={handleLogout}
                  className="text-[0.72rem] text-muted-foreground/70 underline underline-offset-2 transition-colors hover:text-muted-foreground"
                >
                  Clear this sign-in and start over
                </button>
              )}
            </div>
          )}

          {mode === "password" && (
            <div className="flex justify-end">
              <button
                type="button"
                onClick={openForgot}
                className="text-[0.72rem] text-muted-foreground/70 transition-colors hover:text-muted-foreground"
              >
                Forgot password?
              </button>
            </div>
          )}

          <Button
            type="submit"
            className="w-full"
            disabled={
              phase === "signing_in" ||
              phase === "syncing" ||
              requestingCode ||
              !email.trim() ||
              (mode === "password" && !password) ||
              (mode === "create" &&
                (!firstName.trim() || !lastName.trim() || !password || !confirmPassword)) ||
              (mode === "code" && codeSent && !code.trim())
            }
          >
            {phase === "signing_in" ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                {mode === "create" ? "Creating account..." : "Signing in..."}
              </>
            ) : phase === "syncing" ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Syncing skill packs...
              </>
            ) : requestingCode ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Sending code...
              </>
            ) : mode === "code" && !codeSent ? (
              "Send code"
            ) : phase === "error" ? (
              "Try again"
            ) : mode === "create" ? (
              "Create account"
            ) : (
              "Sign in"
            )}
          </Button>

          <div className="space-y-2 text-center">
            {mode === "create" ? (
              <button
                type="button"
                onClick={() => switchMode("password")}
                className="text-[0.72rem] text-muted-foreground/70 transition-colors hover:text-muted-foreground"
              >
                Already have an account? Sign in
              </button>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => switchMode("create")}
                  className="text-[0.72rem] font-medium text-foreground/80 transition-colors hover:text-foreground"
                >
                  Create an account
                </button>
                <div>
                  <button
                    type="button"
                    onClick={() => switchMode(mode === "password" ? "code" : "password")}
                    className="text-[0.72rem] text-muted-foreground/70 transition-colors hover:text-muted-foreground"
                  >
                    {mode === "password" ? "Sign in with a code instead" : "Use password instead"}
                  </button>
                </div>
              </>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
