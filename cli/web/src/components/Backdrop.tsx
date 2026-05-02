import { useGpuTier } from "@nous-research/ui/hooks/use-gpu-tier";

const ELEVATE_BLUEPRINT_BACKGROUND = [
  "linear-gradient(90deg, color-mix(in srgb, var(--midground-base) 5%, transparent) 1px, transparent 1px)",
  "linear-gradient(0deg, color-mix(in srgb, var(--midground-base) 4%, transparent) 1px, transparent 1px)",
  "repeating-linear-gradient(135deg, transparent 0 34px, color-mix(in srgb, var(--midground-base) 5%, transparent) 34px 35px, transparent 35px 68px)",
  "linear-gradient(135deg, color-mix(in srgb, var(--background-base) 88%, #123d78 12%), var(--background-base))",
].join(", ");

/**
 * Elevate's local-first app backdrop.
 *
 * This keeps the depth of the original design-system overlay while removing
 * the inherited filler image that made the dashboard feel too much like
 * the source app. Themes can still provide their own `assets.bg`; otherwise the
 * default texture is a quiet blue blueprint/grid layer.
 *
 *   z-1   bg = `var(--background-base)`, mix-blend-mode: difference
 *   z-2   blueprint texture or theme asset, low opacity, screen
 *   z-99  warm top-left vignette (`var(--warm-glow)`), opacity 0.22, lighten
 *   z-101 noise grain (SVG, ~30% opacity × `--noise-opacity-mul`,
 *         color-dodge) — gated on GPU tier
 *
 * `useGpuTier` returns 0 when WebGL is unavailable, the renderer is a
 * software rasterizer (SwiftShader/llvmpipe), or the user has
 * `prefers-reduced-motion: reduce` set. We skip the animated noise layer
 * in that case so low-power / accessibility-conscious sessions stay crisp,
 * mirroring the DS `<Noise />` component's own opt-out.
 */
export function Backdrop() {
  const gpuTier = useGpuTier();

  return (
    <>
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-[1]"
        style={{
          backgroundColor: "var(--background-base)",
          mixBlendMode: "difference",
        }}
      />

      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-[2]"
        style={
          {
            mixBlendMode: "var(--component-backdrop-filler-blend-mode, screen)",
            opacity: "var(--component-backdrop-filler-opacity, 0.18)",
            backgroundImage: `var(--theme-asset-bg, ${ELEVATE_BLUEPRINT_BACKGROUND})`,
            backgroundSize:
              "var(--component-backdrop-background-size, 96px 96px, 24px 24px, 160px 160px, cover)",
            backgroundPosition:
              "var(--component-backdrop-background-position, center, center, center, center)",
          } as unknown as React.CSSProperties
        }
      />

      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-[99]"
        style={{
          background:
            "radial-gradient(ellipse at 0% 0%, transparent 60%, var(--warm-glow) 100%)",
          mixBlendMode: "lighten",
          opacity: 0.22,
        }}
      />

      {gpuTier > 0 && (
        <div
          aria-hidden
          className="pointer-events-none fixed inset-0 z-[101]"
          style={{
            backgroundImage:
              "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 512 512' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' fill='%23eaeaea' filter='url(%23n)' opacity='0.6'/%3E%3C/svg%3E\")",
            backgroundSize: "512px 512px",
            mixBlendMode: "color-dodge",
            opacity: "calc(0.3 * var(--noise-opacity-mul, 1))",
          }}
        />
      )}
    </>
  );
}
