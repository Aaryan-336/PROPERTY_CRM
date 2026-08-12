import { CallConsole } from "@/components/queue/CallConsole";
import { api } from "@/lib/api";
import type { Paged, QueueItem } from "@/lib/types";

export const metadata = { title: "Calling · Balaji CRM" };

/**
 * The calling session.
 *
 * The whole queue is fetched once and worked through client-side, so logging a
 * call advances to the next lead without a round trip. A caller doing eighty
 * calls in a shift should never wait on a page load between them — and if the
 * connection drops mid-shift, they still have their remaining leads on screen
 * rather than an error page.
 *
 * Scoped by the API to this caller's own assigned leads, like every other read.
 */
export default async function CallSessionPage() {
  const page = await api<Paged<QueueItem>>("/call-queue?limit=50");
  return <CallConsole queue={page.items} total={page.total} />;
}
