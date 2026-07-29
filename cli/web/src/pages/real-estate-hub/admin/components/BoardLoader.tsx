/* ─────────────────────────────────────────────────────────────────
   BoardLoader

   Cute, on-brand loading state for the Admin board. Skyleigh's
   octopus-robot mascot gently bounces over a squash/stretch shadow,
   with three brand-color dots pulsing in sequence underneath. Keyframes
   + classes live in admin.css (".bl-*"). Respects prefers-reduced-motion.

   Brand: navy #182848 · brand blue #5E8AD0 · brand orange #C46340
   ───────────────────────────────────────────────────────────────── */

function BoardLoader({ label }: { label?: string }) {
  return (
    <div className="bl-wrap" role="status" aria-live="polite" aria-busy="true">
      <div className="bl-stage">
        {/* public/octo-loader.png — Vite serves public/ at the web root */}
        <img className="bl-octo" src="/octo-loader.png" alt="" aria-hidden="true" />
        <div className="bl-shadow" aria-hidden="true"></div>
      </div>

      <div className="bl-caption">{label ?? "Pulling up your deals…"}</div>

      <div className="bl-dots" aria-hidden="true">
        <span className="bl-dot bl-dot-1"></span>
        <span className="bl-dot bl-dot-2"></span>
        <span className="bl-dot bl-dot-3"></span>
      </div>

      <span className="bl-sr-only">Loading deals</span>
    </div>
  );
}

export default BoardLoader;
