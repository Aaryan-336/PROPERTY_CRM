"use client";

import { useState } from "react";

import { LogCallSheet } from "@/components/LogCallSheet";
import { LogShowingSheet } from "@/components/LogShowingSheet";
import { BuildingIcon, PhoneIcon } from "@/components/icons";

/**
 * The lead's primary actions, pinned in the bottom third of the screen and
 * clear of the floating nav pill.
 *
 * Equal widths, with "Log call" carrying the accent colour: the two are used
 * often enough that neither should be the fiddly one to hit, and colour
 * already says which is primary without spending width on it. That is as far as
 * DESIGN_RULES' one-primary-action rule can bend before an agent standing in a
 * flat has to go hunting through a menu mid-conversation.
 */
export function ContactActions({
  contactId,
  contactName,
  phone,
  canLogShowing,
  isLead = true,
}: {
  contactId: number;
  contactName: string;
  phone: string | null;
  canLogShowing: boolean;
  isLead?: boolean;
}) {
  const [calling, setCalling] = useState(false);
  const [showing, setShowing] = useState(false);

  return (
    <>
      <div className="above-dock pointer-events-none fixed inset-x-0 z-30 flex justify-center px-4 lg:static lg:bottom-auto lg:justify-start lg:px-0">
        <div className="pointer-events-auto flex w-full max-w-md gap-2 lg:max-w-none">
          <button
            onClick={() => setCalling(true)}
            className="tap flex flex-1 items-center justify-center gap-2 rounded-pill bg-sandstone px-4 text-[15px] font-semibold text-white shadow-float lg:flex-none lg:px-8"
          >
            <PhoneIcon className="h-[18px] w-[18px]" />
            Log call
          </button>

          {canLogShowing && (
            <button
              onClick={() => setShowing(true)}
              className="tap flex flex-1 items-center justify-center gap-2 rounded-pill bg-ink px-4 text-[15px] font-semibold text-white shadow-float lg:flex-none lg:px-8"
            >
              <BuildingIcon className="h-[18px] w-[18px]" />
              Log visit
            </button>
          )}
        </div>
      </div>

      <LogCallSheet
        contactId={contactId}
        contactName={contactName}
        phone={phone}
        isLead={isLead}
        open={calling}
        onClose={() => setCalling(false)}
      />

      {canLogShowing && (
        <LogShowingSheet
          contactId={contactId}
          contactName={contactName}
          open={showing}
          onClose={() => setShowing(false)}
        />
      )}
    </>
  );
}
