import React, { Suspense, lazy } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import "./index.css";

// Route-level code splitting: the public landing page and the terminal
// (recharts, every page module) are large and mutually exclusive on first
// load, so each is only fetched when its route is actually visited.
const App = lazy(() => import("./App"));
const Landing = lazy(() => import("./pages/Landing"));

function RouteFallback() {
  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#080e1a", color: "#94a3b8", fontFamily: "monospace", fontSize: 12 }}>
      Loading…
    </div>
  );
}

// The terminal (App.tsx) keeps its existing internal page-switching
// behavior unchanged — it is only mounted at /terminal/* instead of at the
// site root. There is no authentication system in this repository (see
// CHANGELOG), so this split does not gate access to trading data; it only
// separates the public marketing surface from the operator terminal.
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/terminal/*" element={<App />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  </React.StrictMode>
);
