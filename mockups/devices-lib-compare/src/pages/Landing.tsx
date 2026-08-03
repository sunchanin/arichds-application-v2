import { Link } from "react-router-dom";

interface CardDef {
  href: string;
  title: string;
  note: string;
  accent: string;
}

const CARDS: CardDef[] = [
  {
    href: "/mantine",
    title: "Mantine v9",
    note: "@mantine/core + @mantine/dates, teal-family primary, tuned for a dense operator UI.",
    accent: "#0c8599",
  },
  {
    href: "/shadcn",
    title: "shadcn/ui + Tailwind v4",
    note: "Hand-built shadcn-style components (zinc palette) + TanStack Table + the official shadcn Date Picker.",
    accent: "#18181b",
  },
];

export default function Landing() {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "48px 24px",
        fontFamily: "system-ui, 'Segoe UI', Roboto, sans-serif",
      }}
    >
      <div style={{ maxWidth: 760, width: "100%" }}>
        <p
          style={{
            textTransform: "uppercase",
            letterSpacing: 1.2,
            fontSize: 12,
            fontWeight: 600,
            color: "#71717a",
            margin: "0 0 8px",
          }}
        >
          arichds-application-v2 · mockup
        </p>
        <h1 style={{ fontSize: 32, margin: "0 0 8px", color: "#18181b" }}>
          Devices page — library comparison
        </h1>
        <p style={{ color: "#52525b", margin: "0 0 12px", maxWidth: 640, lineHeight: 1.5 }}>
          v1's real Devices page — split tree + form layout, same sections, same
          fields — rebuilt with two candidate UI libraries so the owner can pick
          one for the v2 rewrite.
        </p>
        <p
          style={{
            color: "#52525b",
            margin: "0 0 32px",
            maxWidth: 640,
            lineHeight: 1.5,
            background: "#f4f4f5",
            border: "1px solid #e4e4e7",
            borderRadius: 8,
            padding: "10px 14px",
            fontSize: 13,
          }}
        >
          <strong>AntD v6 reference:</strong> not re-mocked here — v1 itself
          (<code>cewe-fe</code>) already is the AntD baseline, running in
          production-grade code today. See the README comparison table for
          how it stacks up against the two variants below.
        </p>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
            gap: 16,
          }}
        >
          {CARDS.map((card) => (
            <Link
              key={card.href}
              to={card.href}
              style={{
                textDecoration: "none",
                display: "block",
                background: "#fff",
                border: "1px solid #e4e4e7",
                borderRadius: 12,
                padding: 20,
                boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
                transition: "box-shadow 0.15s, transform 0.15s",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.boxShadow = "0 4px 14px rgba(0,0,0,0.08)";
                e.currentTarget.style.transform = "translateY(-2px)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.boxShadow = "0 1px 2px rgba(0,0,0,0.04)";
                e.currentTarget.style.transform = "translateY(0)";
              }}
            >
              <div
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: 8,
                  background: card.accent,
                  marginBottom: 14,
                }}
              />
              <h2 style={{ fontSize: 16, margin: "0 0 6px", color: "#18181b" }}>
                {card.title}
              </h2>
              <p style={{ fontSize: 13, color: "#71717a", margin: 0, lineHeight: 1.5 }}>
                {card.note}
              </p>
            </Link>
          ))}
        </div>

        <p style={{ marginTop: 32, fontSize: 12, color: "#a1a1aa" }}>
          Throwaway mockup — not part of the production app.
        </p>
      </div>
    </div>
  );
}
