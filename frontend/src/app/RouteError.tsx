import { isRouteErrorResponse, useRouteError } from "react-router-dom";

/** Shown when a page fails to load or render (e.g. a chunk failed after a deploy). */
export function RouteError() {
  const error = useRouteError();
  const notFound = isRouteErrorResponse(error) && error.status === 404;
  return (
    <main className="mx-auto max-w-md px-6 py-24 text-center">
      <h1 className="text-xl font-semibold text-ink">
        {notFound ? "This page doesn't exist" : "This page couldn't load"}
      </h1>
      <p className="mt-3 text-base text-slate">
        {notFound
          ? "Check the address, or go back to the start."
          : "Reload the page. If it keeps happening, the app may have just been updated."}
      </p>
      <div className="mt-6 flex justify-center gap-3">
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="h-10 rounded-control bg-ink px-4 text-sm font-semibold text-surface"
        >
          Reload page
        </button>
        <a href="/" className="flex h-10 items-center rounded-control border border-line bg-surface px-4 text-sm font-semibold text-ink">
          Go to start
        </a>
      </div>
    </main>
  );
}
