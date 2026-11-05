import "@/styles/index.css";
import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { Toaster } from "sonner";
import { router } from "@/app/router";
import { TooltipProvider } from "@/components/ui/tooltip";
import { queryClient } from "@/lib/query";

const root = document.getElementById("root");
if (!root) throw new Error("#root missing");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <RouterProvider router={router} />
        <Toaster
          position="bottom-right"
          toastOptions={{
            className: "!rounded-panel !border-line !bg-surface !font-sans !text-sm !text-ink !shadow-float",
          }}
        />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
);
