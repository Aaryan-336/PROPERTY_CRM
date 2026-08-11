export const metadata = { title: "Offline · Balaji CRM" };

export default function OfflinePage() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center bg-parchment px-6 text-center">
      <div className="max-w-sm">
        <p className="font-display text-2xl text-ink">You&rsquo;re offline</p>
        <p className="mt-3 text-sm leading-relaxed text-slate">
          Leads and inventory you opened recently are still available. Anything
          new — including logging a call or a site visit — needs a connection,
          so nothing gets recorded with the wrong time.
        </p>
        <p className="mt-6 text-xs text-slate">
          This page will work again as soon as you&rsquo;re back on signal.
        </p>
      </div>
    </main>
  );
}
