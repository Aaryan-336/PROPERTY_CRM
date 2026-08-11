import { redirect } from "next/navigation";

import { FeedConsole } from "@/components/feed/FeedConsole";
import { api } from "@/lib/api";
import { getCurrentUser } from "@/lib/session";
import type {
  IngestionStatus,
  Paged,
  Property,
  WhatsAppGroup,
  WhatsAppMessage,
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
  if (!user) redirect("/login");
  if (user.role !== "owner") redirect("/");

  const [status, groups, recent, review] = await Promise.all([
    api<IngestionStatus>("/whatsapp/ingestion-status"),
    api<WhatsAppGroup[]>("/whatsapp/groups"),
    api<Paged<WhatsAppMessage>>("/whatsapp/messages?limit=25"),
    api<Paged<Property>>(
      "/properties?source=whatsapp_group&review_state=needs_review&limit=10",
    ),
  ]);

  return (
    <FeedConsole
      status={status}
      groups={groups}
      recent={recent.items}
      needsReview={review.items}
    />
  );
}
