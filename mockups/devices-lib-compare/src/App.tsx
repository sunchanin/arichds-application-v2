import { Suspense, lazy } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Landing from "./pages/Landing";

// Lazy per route: each variant only pulls its UI library into its own chunk,
// so `pnpm build` output shows a fair per-library bundle size.
// The AntD variant was dropped (see README) — v1 (cewe-fe, already built with
// AntD) is the reference for that column instead of a re-themed mockup.
const MantineDevicesPage = lazy(() => import("./pages/mantine/MantineDevicesPage"));
const ShadcnDevicesPage = lazy(() => import("./pages/shadcn/ShadcnDevicesPage"));

const Loading = () => (
  <div style={{ padding: 40, fontFamily: "system-ui, sans-serif", color: "#666" }}>
    Loading…
  </div>
);

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/mantine" element={<MantineDevicesPage />} />
          <Route path="/shadcn" element={<ShadcnDevicesPage />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
