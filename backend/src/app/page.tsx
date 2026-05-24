import Link from "next/link";

export default function Page() {
  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: 16,
        background:
          "radial-gradient(circle at 20% 0%, rgba(217, 119, 87, 0.06), transparent 50%), radial-gradient(circle at 80% 100%, rgba(122, 158, 135, 0.04), transparent 50%), var(--bg)",
      }}
    >
      <div className="fade-in" style={{ textAlign: "center", maxWidth: 420 }}>
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 12,
            marginBottom: 20,
          }}
        >
          <svg width="44" height="44" viewBox="0 0 28 28" fill="none" aria-hidden="true">
            <rect width="28" height="28" rx="7" fill="var(--accent)" />
            <path d="M9 9h10v2.5h-7.5v3h6V17h-6v3H19V22.5H9V9z" fill="#fff" />
          </svg>
        </div>
        <h1
          style={{
            fontSize: 32,
            fontWeight: 600,
            margin: 0,
            letterSpacing: "-0.02em",
          }}
        >
          Elevate HQ
        </h1>
        <p
          style={{
            color: "var(--text-dim)",
            marginTop: 8,
            marginBottom: 24,
            fontSize: 14,
          }}
        >
          Control panel for users, organizations, and entitlements.
        </p>
        <div
          style={{
            display: "inline-flex",
            gap: 8,
            flexWrap: "wrap",
            justifyContent: "center",
          }}
        >
          <Link
            href="/signup"
            style={{
              display: "inline-flex",
              alignItems: "center",
              padding: "8px 16px",
              background: "var(--accent)",
              color: "#fff",
              border: "1px solid var(--accent)",
              borderRadius: "var(--r-md)",
              fontSize: 13,
              fontWeight: 500,
              textDecoration: "none",
              transition: "background 120ms",
            }}
          >
            Create account
          </Link>
          <Link
            href="/admin/login"
            style={{
              display: "inline-flex",
              alignItems: "center",
              padding: "8px 16px",
              background: "var(--bg-elev-2)",
              color: "var(--text)",
              border: "1px solid var(--border)",
              borderRadius: "var(--r-md)",
              fontSize: 13,
              fontWeight: 500,
              textDecoration: "none",
            }}
          >
            Sign in
          </Link>
        </div>
      </div>
    </main>
  );
}
