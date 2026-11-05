// Sign up / log in (docs/frontend.md §6.2): one centred form, field errors from zod, server
// errors in one line under the button.
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { api, unwrap } from "@/lib/api";
import { setToken } from "@/lib/auth";
import { PRODUCT_NAME } from "@/lib/brand";
import { ApiError, messageOf } from "@/lib/errors";

const email = z.email("Enter a valid email address.");
const signupSchema = z.object({
  org_name: z.string().trim().min(1, "Enter your organization's name.").max(120, "Keep it under 120 characters."),
  email,
  password: z.string().min(8, "Use at least 8 characters.").max(128, "Use at most 128 characters."),
});
const loginSchema = z.object({ email, password: z.string().min(1, "Enter your password.") });

type SignupValues = z.infer<typeof signupSchema>;
type LoginValues = z.infer<typeof loginSchema>;

function AuthLayout({ title, children, footer }: { title: string; children: React.ReactNode; footer: React.ReactNode }) {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center px-4 py-12">
      <Link to="/" className="mb-8 text-lg font-semibold text-ink">
        {PRODUCT_NAME}
      </Link>
      <div className="w-full max-w-sm rounded-panel border border-line bg-surface p-6 sm:p-8">
        <h1 className="text-lg font-semibold text-ink">{title}</h1>
        <div className="mt-6">{children}</div>
      </div>
      <p className="mt-6 text-sm text-slate">{footer}</p>
    </main>
  );
}

function useAfterAuth() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  return (token: string) => {
    setToken(token);
    queryClient.clear(); // nothing from a previous session may leak into this one
    const next = params.get("next");
    navigate(next && next.startsWith("/app") ? next : "/app/documents", { replace: true });
  };
}

export function Signup() {
  const after = useAfterAuth();
  const [serverError, setServerError] = useState<React.ReactNode>(null);
  const form = useForm<SignupValues>({ resolver: zodResolver(signupSchema), mode: "onTouched" });
  const { errors, isSubmitting } = form.formState;

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    try {
      const body = await unwrap(api.POST("/auth/register", { body: values }));
      after(body.token);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setServerError(
          <>
            That email already has a workspace.{" "}
            <Link to="/login" className="font-semibold text-teal underline underline-offset-4">
              Log in instead.
            </Link>
          </>,
        );
      } else {
        if (e instanceof ApiError) {
          for (const [field, message] of Object.entries(e.fieldErrors)) {
            if (field in values) form.setError(field as keyof SignupValues, { message });
          }
        }
        setServerError(messageOf(e, "Couldn't create the workspace. Try again."));
      }
    }
  });

  return (
    <AuthLayout
      title="Create a workspace"
      footer={
        <>
          Already have one?{" "}
          <Link to="/login" className="font-semibold text-teal underline-offset-4 hover:underline">
            Log in
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <Field id="org_name" label="Organization name" error={errors.org_name?.message}>
          <Input id="org_name" autoComplete="organization" autoFocus aria-invalid={!!errors.org_name}
            aria-describedby="org_name-msg" {...form.register("org_name")} />
        </Field>
        <Field id="email" label="Work email" error={errors.email?.message}>
          <Input id="email" type="email" autoComplete="email" aria-invalid={!!errors.email}
            aria-describedby="email-msg" {...form.register("email")} />
        </Field>
        <Field id="password" label="Password" error={errors.password?.message} hint="At least 8 characters.">
          <Input id="password" type="password" autoComplete="new-password" aria-invalid={!!errors.password}
            aria-describedby="password-msg" {...form.register("password")} />
        </Field>
        <Button type="submit" className="w-full" disabled={isSubmitting}>
          {isSubmitting ? "Creating workspace…" : "Create workspace"}
        </Button>
        {serverError ? (
          <p role="alert" className="text-sm text-notmet">
            {serverError}
          </p>
        ) : null}
      </form>
    </AuthLayout>
  );
}

export function Login() {
  const after = useAfterAuth();
  const [params] = useSearchParams();
  const [serverError, setServerError] = useState<string | null>(null);
  const form = useForm<LoginValues>({ resolver: zodResolver(loginSchema), mode: "onTouched" });
  const { errors, isSubmitting } = form.formState;

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    try {
      const body = await unwrap(api.POST("/auth/login", { body: values }));
      after(body.token);
    } catch (e) {
      setServerError(messageOf(e, "Couldn't log in. Try again."));
    }
  });

  return (
    <AuthLayout
      title="Log in"
      footer={
        <>
          New here?{" "}
          <Link to="/signup" className="font-semibold text-teal underline-offset-4 hover:underline">
            Create a workspace
          </Link>
        </>
      }
    >
      {params.get("expired") ? (
        <p className="mb-4 rounded-control bg-teal-tint px-3 py-2 text-sm text-ink" role="status">
          Your session ended. Log in again to continue.
        </p>
      ) : null}
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <Field id="email" label="Email" error={errors.email?.message}>
          <Input id="email" type="email" autoComplete="email" autoFocus aria-invalid={!!errors.email}
            aria-describedby="email-msg" {...form.register("email")} />
        </Field>
        <Field id="password" label="Password" error={errors.password?.message}>
          <Input id="password" type="password" autoComplete="current-password" aria-invalid={!!errors.password}
            aria-describedby="password-msg" {...form.register("password")} />
        </Field>
        <Button type="submit" className="w-full" disabled={isSubmitting}>
          {isSubmitting ? "Logging in…" : "Log in"}
        </Button>
        {serverError ? (
          <p role="alert" className="text-sm text-notmet">
            {serverError}
          </p>
        ) : null}
      </form>
    </AuthLayout>
  );
}
