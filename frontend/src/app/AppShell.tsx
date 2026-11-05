// App shell (docs/frontend.md §6.3): 232 px sidebar, collapsing to a top bar under 768 px.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, FileText, LogOut, Menu, MessageSquareText, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Navigate, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Skeleton } from "@/components/ui/states";
import { api, unwrap } from "@/lib/api";
import { clearToken, getToken } from "@/lib/auth";
import { PRODUCT_NAME } from "@/lib/brand";
import { cn } from "@/lib/cn";

const NAV = [
  { to: "/app/documents", label: "Documents", icon: FileText },
  { to: "/app/assistant", label: "Assistant", icon: MessageSquareText },
  { to: "/app/usage", label: "Usage", icon: BarChart3 },
];

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => unwrap(api.GET("/api/admin/me")),
    staleTime: 5 * 60_000,
  });
}

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <ul className="space-y-0.5">
      {NAV.map(({ to, label, icon: Icon }) => (
        <li key={to}>
          <NavLink
            to={to}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2.5 rounded-control px-3 py-2 text-sm",
                isActive ? "bg-teal-tint font-semibold text-teal" : "text-slate hover:bg-canvas hover:text-ink",
              )
            }
          >
            <Icon className="size-4" strokeWidth={1.75} aria-hidden="true" />
            {label}
          </NavLink>
        </li>
      ))}
    </ul>
  );
}

function Account({ onLogout }: { onLogout: () => void }) {
  const me = useMe();
  return (
    <div className="border-t border-line pt-4">
      {me.isPending ? (
        <Skeleton className="h-5 w-32" />
      ) : (
        <p className="truncate text-sm font-semibold text-ink" title={me.data?.org.name}>
          {me.data?.org.name ?? "Your workspace"}
        </p>
      )}
      {me.data ? <p className="truncate text-xs text-slate">{me.data.email}</p> : null}
      <button
        type="button"
        onClick={onLogout}
        className="mt-3 -ml-1 flex items-center gap-2 rounded-control px-1 py-1 text-sm text-slate hover:text-ink"
      >
        <LogOut className="size-4" strokeWidth={1.75} aria-hidden="true" />
        Log out
      </button>
    </div>
  );
}

export function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => setMenuOpen(false), [location.pathname]);

  if (!getToken()) {
    return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />;
  }

  const logout = () => {
    clearToken();
    queryClient.clear();
    navigate("/login", { replace: true });
  };

  return (
    <div className="min-h-dvh md:grid md:grid-cols-[232px_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-2 focus:rounded-control focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      {/* Sidebar (768 px and up) */}
      <div className="hidden border-r border-line bg-surface md:block">
      <aside className="sticky top-0 flex h-dvh flex-col px-4 py-5">
        <NavLink to="/app/documents" className="px-3 text-lg font-semibold text-ink">
          {PRODUCT_NAME}
        </NavLink>
        <nav aria-label="Main" className="mt-8 flex-1">
          <NavItems />
        </nav>
        <Account onLogout={logout} />
      </aside>
      </div>

      {/* Top bar (under 768 px) */}
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-surface px-4 py-3 md:hidden">
        <span className="text-lg font-semibold text-ink">{PRODUCT_NAME}</span>
        <button
          type="button"
          className="rounded-control p-2 text-slate hover:bg-canvas"
          aria-expanded={menuOpen}
          aria-controls="mobile-nav"
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          onClick={() => setMenuOpen((o) => !o)}
        >
          {menuOpen ? <X className="size-5" strokeWidth={1.75} /> : <Menu className="size-5" strokeWidth={1.75} />}
        </button>
      </header>
      {menuOpen ? (
        <div id="mobile-nav" className="border-b border-line bg-surface px-4 py-4 md:hidden">
          <nav aria-label="Main">
            <NavItems onNavigate={() => setMenuOpen(false)} />
          </nav>
          <div className="mt-4">
            <Account onLogout={logout} />
          </div>
        </div>
      ) : null}

      <main id="main" className="min-w-0 px-4 py-8 sm:px-8 lg:px-12">
        <div className="mx-auto max-w-5xl">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

export function PageHeader({ title, action, children }: { title: string; action?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="mb-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-xl font-semibold text-ink">{title}</h1>
        {action}
      </div>
      {children}
    </div>
  );
}
