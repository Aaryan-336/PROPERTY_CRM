"use client";

import { FilterBar } from "@/components/FilterBar";
import type { User } from "@/lib/types";

/** Agent filter for the "who showed what to whom" view. No free-text search:
 *  the three axes API_SPEC defines are agent, property and client. */
export function ShowingsFilter({ agents }: { agents: User[] }) {
  return (
    <FilterBar
      showSearch={false}
      selects={[
        {
          name: "agent_id",
          label: "Agent",
          options: agents.map((a) => ({ value: String(a.id), label: a.name })),
        },
      ]}
    />
  );
}
