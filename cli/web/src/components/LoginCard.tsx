import { useCallback, useEffect, useState } from "react";
import { Check, ChevronDown, Loader2, LogOut, Package } from "lucide-react";
import { api } from "@/lib/api";
import type {
  LicenseStatusResponse,
  LicenseActivateResponse,
} from "@/lib/api-types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

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

export function LoginCard({ onAuthChange }: Props) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [backendUrl, setBackendUrl] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [licenseStatus, setLicenseStatus] = useState<LicenseStatusResponse | null>(null);
  const [activationResult, setActivationResult] = useState<LicenseActivateResponse | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      const status = await api.getLicenseStatus();
      setLicenseStatus(status);
      if (status.authenticated) {
        setPhase("authenticated");
        onAuthChange?.(true, status.packs);
      } else {
        setPhase("logged_out");
        onAuthChange?.(false, status.packs);
      }
    } catch {
      setPhase("logged_out");
    }
  }, [onAuthChange]);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  const handleSignIn = async () => {
    if (!email.trim() || !password) return;
    setPhase("signing_in");
    setError(null);

    try {
      const result = await api.activateLicense(
        email.trim(),
        password,
        backendUrl.trim() || undefined,
      );
      setActivationResult(result);

      if (result.skill_count > 0) {
        setPhase("success");
      } else {
        setPhase("syncing");
        try {
          await api.syncLicenseSkills();
        } catch {
          // skill sync is best-effort
        }
        setPhase("success");
      }

      onAuthChange?.(true, result.packs);
      window.dispatchEvent(new Event("elevate:auth-changed"));
      await loadStatus();
    } catch (err: unknown) {
      setPhase("error");
      const message = err instanceof Error ? err.message : String(err);
      if (message.includes("401") || message.includes("Invalid")) {
        setError("Invalid email or password.");
      } else if (message.includes("402")) {
        setError("No active subscription. Contact Elevation Real Estate HQ.");
      } else {
        setError(message);
      }
    }
  };

  const handleLogout = async () => {
    try {
      const result = await api.logoutLicense();
      setLicenseStatus(null);
      setActivationResult(null);
      setPhase("logged_out");
      setEmail("");
      setPassword("");
      onAuthChange?.(false, result.packs);
      window.dispatchEvent(new Event("elevate:auth-changed"));
    } catch {
      setPhase("logged_out");
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
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2.5 py-1 text-[0.72rem] font-semibold text-emerald-600">
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
                    className="inline-flex items-center gap-1 rounded-md bg-primary/10 px-2 py-0.5 text-[0.72rem] font-medium text-primary"
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
                    className="flex items-center gap-2.5 rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-3 py-2"
                  >
                    <Check className="h-4 w-4 text-emerald-500" />
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
      <CardHeader>
        <CardTitle>Sign in to Elevation HQ</CardTitle>
        <CardDescription>
          Enter your Elevation Real Estate HQ credentials to unlock your skill packs.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={(e) => { e.preventDefault(); handleSignIn(); }}
          className="space-y-3"
        >
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
              disabled={phase === "signing_in" || phase === "syncing"}
              autoComplete="email"
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="login-password" className="text-xs font-medium text-muted-foreground">
              Password
            </label>
            <Input
              id="login-password"
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={phase === "signing_in" || phase === "syncing"}
              autoComplete="current-password"
            />
          </div>

          <button
            type="button"
            onClick={() => setShowAdvanced((v) => !v)}
            className={cn(
              "flex items-center gap-1 text-[0.72rem] text-muted-foreground/60 transition-colors hover:text-muted-foreground",
              showAdvanced && "text-muted-foreground",
            )}
          >
            <ChevronDown className={cn("h-3 w-3 transition-transform", showAdvanced && "rotate-180")} />
            Advanced
          </button>
          {showAdvanced && (
            <div className="space-y-1.5">
              <label htmlFor="login-backend" className="text-xs font-medium text-muted-foreground">
                Backend URL
              </label>
              <Input
                id="login-backend"
                type="url"
                placeholder="https://api.elevationrealestatehq.com"
                value={backendUrl}
                onChange={(e) => setBackendUrl(e.target.value)}
                disabled={phase === "signing_in" || phase === "syncing"}
              />
            </div>
          )}

          {error && (
            <p className="rounded-lg bg-destructive/10 px-3 py-2 text-xs font-medium text-destructive">
              {error}
            </p>
          )}

          <Button
            type="submit"
            className="w-full"
            disabled={phase === "signing_in" || phase === "syncing" || !email.trim() || !password}
          >
            {phase === "signing_in" ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Signing in...
              </>
            ) : phase === "syncing" ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Syncing skill packs...
              </>
            ) : phase === "error" ? (
              "Try again"
            ) : (
              "Sign in"
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
