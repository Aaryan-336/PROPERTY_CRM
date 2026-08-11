import { LoginForm } from "@/components/LoginForm";

export const metadata = { title: "Sign in · Balaji CRM" };

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ expired?: string }>;
}) {
  const { expired } = await searchParams;

  return (
    <main className="flex min-h-dvh flex-col justify-center bg-parchment px-5 py-10">
      <div className="mx-auto w-full max-w-sm">
        <div className="mb-8">
          <p className="font-display text-3xl leading-none text-ink">Balaji</p>
          <p className="tabular mt-2 text-[11px] uppercase tracking-[0.22em] text-slate">
            Brokerage CRM
          </p>
        </div>

        {expired && (
          <div className="mb-4 rounded-tile bg-ink px-4 py-3 text-sm text-white">
            Your session ended. Please sign in again.
          </div>
        )}

        <LoginForm />

        <p className="mt-8 text-xs leading-relaxed text-slate">
          Activity in this app is logged and visible to the firm owner. That
          includes leads viewed, calls logged and properties shown.
        </p>
      </div>
    </main>
  );
}
