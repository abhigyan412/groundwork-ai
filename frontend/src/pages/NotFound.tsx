import { Link } from "react-router-dom";

export function NotFound() {
  return (
    <main className="mx-auto max-w-md px-6 py-24 text-center">
      <h1 className="text-xl font-semibold text-ink">This page doesn't exist</h1>
      <p className="mt-3 text-base text-slate">Check the address, or go back to the start.</p>
      <Link to="/" className="mt-6 inline-flex h-10 items-center rounded-control bg-ink px-4 text-sm font-semibold text-surface">
        Go to start
      </Link>
    </main>
  );
}
