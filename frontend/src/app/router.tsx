// Routes (docs/frontend.md §3). Every page group is lazy-loaded, so the widget chunk (/a/:token)
// never contains dashboard code and the dashboard never ships widget code.
import { createBrowserRouter, Navigate } from "react-router-dom";
import { RouteError } from "./RouteError";

export const router = createBrowserRouter([
  { path: "/", lazy: async () => ({ Component: (await import("@/pages/Landing")).Landing }), errorElement: <RouteError /> },
  { path: "/signup", lazy: async () => ({ Component: (await import("@/pages/Auth")).Signup }), errorElement: <RouteError /> },
  { path: "/login", lazy: async () => ({ Component: (await import("@/pages/Auth")).Login }), errorElement: <RouteError /> },
  {
    path: "/app",
    lazy: async () => ({ Component: (await import("./AppShell")).AppShell }),
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Navigate to="documents" replace /> },
      { path: "documents", lazy: async () => ({ Component: (await import("@/pages/Documents")).Documents }) },
      { path: "assistant", lazy: async () => ({ Component: (await import("@/pages/Assistant")).Assistant }) },
      { path: "usage", lazy: async () => ({ Component: (await import("@/pages/Usage")).Usage }) },
    ],
  },
  {
    path: "/a/:token",
    lazy: async () => ({ Component: (await import("@/widget/WidgetPage")).WidgetPage }),
    errorElement: <RouteError />,
  },
  { path: "*", lazy: async () => ({ Component: (await import("@/pages/NotFound")).NotFound }) },
]);
