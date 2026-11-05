import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-10 w-full rounded-control border border-line bg-surface px-3 text-base text-ink",
        "placeholder:text-slate/70 aria-[invalid=true]:border-notmet",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

type FieldProps = {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  children: ReactNode;
};

/** Label + control + one line of error or hint. The control should set aria-describedby. */
export function Field({ id, label, error, hint, children }: FieldProps) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-semibold text-ink">
        {label}
      </label>
      {children}
      {error ? (
        <p id={`${id}-msg`} className="text-sm text-notmet" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-msg`} className="text-sm text-slate">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
