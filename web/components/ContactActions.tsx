"use client";

import { useState } from "react";

import { LogCallSheet } from "@/components/LogCallSheet";
import { LogShowingSheet } from "@/components/LogShowingSheet";
import { BuildingIcon, PhoneIcon } from "@/components/icons";

/**
 * The lead's primary actions, pinned in the bottom third of the screen and
 * clear of the floating nav pill.
 *
 * One primary action ("Log call" — the most frequent by a wide margin);
 * logging a showing sits beside it as the secondary, which is as far as
 * DESIGN_RULES' one-primary-action rule can bend before an agent standing in a
 * flat has to go hunting through a menu mid-conversation.
 */
export function ContactActions({
  contactId,
  contactName,
  phone,
  canLogShowing,
}: {
  contactId: number;
  contactName: string;
  phone: string | null;
  canLogShowing: boolean;
}) {
  const [calling, setCalling] = useState(false);
  const [showing, setShowing] = useState(false);

  return (
    <>
      <div className="safe-bottom pointer-events-none fixed inset-x-0 bottom-0 z-30 flex justify-center px-4 pb-[76px] lg:static lg:justify-start lg:px-0 lg:pb-0">
        <div className="pointer-events-auto flex w-full max-w-md gap-2 lg:max-w-none">
          <button
            onClick={() => setCalling(true)}
            className="tap flex flex-[2] items-center justify-center gap-2 rounded-pill bg-sandstone px-5 text-[15px] font-semibold text-white shadow-float lg:flex-none lg:px-8"
          >
            <PhoneIcon className="h-[18px] w-[18px]" />
            Log call
          </button>

          {canLogShowing && (
            <button
              onClick={() => setShowing(true)}
              className="tap flex flex-1 items-center justify-center gap-2 rounded-pill bg-ink px-4 text-[15px] font-semibold text-white shadow-float lg:flex-none lg:px-6"
            >
              <BuildingIcon className="h-[18px] w-[18px]" />
              <span className="hidden sm:inline">Log visit</span>
              <span className="sm:hidden">Visit</span>
            </button>
          )}
        </div>
      </div>

      <LogCallSheet
        contactId={contactId}
        contactName={contactName}
        phone={phone}
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
