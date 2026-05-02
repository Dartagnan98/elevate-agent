/**
 * Elevate's local-first app backdrop.
 *
 * The previous blueprint/noise texture made the shell feel like a skin. The
 * new app chrome is intentionally quiet: a solid product canvas with a soft
 * vertical wash so dashboard pages and chat share the same visual language.
 */
export function Backdrop() {
  return (
    <>
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-[1]"
        style={{
          backgroundColor: "var(--background-base)",
        }}
      />

      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-[2]"
        style={{
          background:
            "linear-gradient(180deg, color-mix(in srgb, var(--midground-base) 3%, transparent), transparent 28rem)",
          opacity: "var(--component-backdrop-filler-opacity, 1)",
        }}
      />

      <div
        aria-hidden
        className="pointer-events-none fixed inset-x-0 top-0 z-[3] h-px"
        style={{
          background:
            "linear-gradient(90deg, transparent, color-mix(in srgb, var(--midground-base) 22%, transparent), transparent)",
        }}
      />
    </>
  );
}
