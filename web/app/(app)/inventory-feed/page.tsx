import { redirect } from "next/navigation";

import { ConnectWhatsApp } from "@/components/feed/ConnectWhatsApp";
import { FeedConsole } from "@/components/feed/FeedConsole";
import { GroupPicker } from "@/components/feed/GroupPicker";
import { api, apiOptional } from "@/lib/api";
import { SESSION_EXPIRED_ROUTE, getCurrentUser } from "@/lib/session";
import type {
  IngestionStatus,
  Paged,
  Property,
  WhatsAppGroup,
  WhatsAppGroupCandidate,
  WhatsAppMessage,
  WhatsAppSession,
} from "@/lib/types";

export const metadata = { title: "Inventory feed · Balaji CRM" };

/**
 * Owner's WhatsApp ingestion console.
 *
 * ROLES_PERMISSIONS.md: "Configure WhatsApp ingestion groups — Owner only".
 * The redirect is a courtesy; the API refuses these calls for any other role
 * regardless of what the UI renders.
 */
export default async function InventoryFeedPage() {
  const user = await getCurrentUser();
  if (!user) redirect(SESSION_EXPIRED_ROUTE);
  if (user.role !== "owner") redirect("/");

  const [status, groups, recent, review, session, candidates] = await Promise.all([
    api<IngestionStatus>("/whatsapp/ingestion-status"),
    api<WhatsAppGroup[]>("/whatsapp/groups"),
    api<Paged<WhatsAppMessage>>("/whatsapp/messages?limit=25"),
    api<Paged<Property>>(
      "/properties?source=whatsapp_group&review_state=needs_review&limit=10",
    ),
    api<WhatsAppSession>("/whatsapp/session"),
    // apiOptional: the picker is a convenience over the manual add form, and a
    // frontend release can reach Vercel before the API that serves this does.
    // An empty picker is a worse screen; a 500 is a broken one.
    apiOptional<WhatsAppGroupCandidate[]>("/whatsapp/available-groups"),
  ]);

  return (
    <div className="space-y-5">
      {/* Above the console on purpose: none of the rest of this screen means
          anything until an account is linked, and the first thing an owner
          opening it needs to know is whether one is. */}
      <ConnectWhatsApp initial={session} />
      {/* Then which groups to read — the second half of setting this up, and
          the step that used to send the owner to a terminal. */}
      <GroupPicker initial={candidates ?? []} session={session} />
      <FeedConsole
        status={status}
        groups={groups}
        recent={recent.items}
        needsReview={review.items}
      />
    </div>
  );
}
