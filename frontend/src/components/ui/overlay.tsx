// Restyled Radix primitives: Dialog (and a side Sheet), DropdownMenu, Tooltip.
import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as Menu from "@radix-ui/react-dropdown-menu";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({
  title,
  description,
  children,
  side = false,
}: {
  title: string;
  description?: ReactNode;
  children: ReactNode;
  side?: boolean;
}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-ink/30" />
      <DialogPrimitive.Content
        className={cn(
          "fixed z-50 bg-surface shadow-float focus:outline-none",
          side
            ? "inset-y-0 right-0 flex w-full max-w-xl flex-col border-l border-line"
            : "top-1/2 left-1/2 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-panel p-6",
        )}
      >
        <div className={cn("flex items-start justify-between gap-4", side && "border-b border-line px-6 py-4")}>
          <DialogPrimitive.Title className="text-lg font-semibold text-ink">{title}</DialogPrimitive.Title>
          <DialogPrimitive.Close
            className="-m-1 rounded-control p-1 text-slate hover:bg-canvas hover:text-ink"
            aria-label="Close"
          >
            <X className="size-5" strokeWidth={1.75} />
          </DialogPrimitive.Close>
        </div>
        {description ? (
          <DialogPrimitive.Description className={cn("mt-2 text-sm text-slate", side && "px-6")}>
            {description}
          </DialogPrimitive.Description>
        ) : (
          <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
        )}
        <div className={cn(side ? "flex-1 overflow-y-auto px-6 py-5" : "mt-5")}>{children}</div>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export const DropdownMenu = Menu.Root;
export const DropdownMenuTrigger = Menu.Trigger;

export function DropdownMenuContent({ children }: { children: ReactNode }) {
  return (
    <Menu.Portal>
      <Menu.Content
        align="end"
        sideOffset={4}
        className="z-50 min-w-40 rounded-panel border border-line bg-surface p-1 shadow-float"
      >
        {children}
      </Menu.Content>
    </Menu.Portal>
  );
}

export function DropdownMenuItem({
  children,
  onSelect,
  danger = false,
}: {
  children: ReactNode;
  onSelect: () => void;
  danger?: boolean;
}) {
  return (
    <Menu.Item
      onSelect={onSelect}
      className={cn(
        "flex cursor-pointer items-center gap-2 rounded-control px-3 py-2 text-sm outline-none select-none",
        "data-[highlighted]:bg-canvas [&_svg]:size-4",
        danger ? "text-notmet" : "text-ink",
      )}
    >
      {children}
    </Menu.Item>
  );
}

export { Tooltip, TooltipProvider } from "./tooltip";
