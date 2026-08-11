"use client";

import { useEffect, useState } from "react";

/**
 * Agents work in basements, lifts and half-built towers. DESIGN_RULES.md asks
 * for connection state to be explicit rather than inferred from a spinner that
 * never resolves, so this says plainly what is happening and what will happen
 * to anything they log.
 */
export function OfflineBanner() {
  const [offline, setOffline] = useState(false);
  const [justReconnected, setJustReconnected] = useState(false);

  useEffect(() => {
    setOffline(!navigator.onLine);

    function goOffline() {
      setOffline(true);
      setJustReconnected(false);
    }
    function goOnline() {
      setOffline(false);
      setJustReconnected(true);
      setTimeout(() => setJustReconnected(false), 3000);
    }

    window.addEventListener("offline", goOffline);
    window.addEventListener("online", goOnline);
    return () => {
      window.removeEventListener("offline", goOffline);
      window.removeEventListener("online", goOnline);
    };
  }, []);

  if (!offline && !justReconnected) return null;

  return (
    <div
      role="status"
      className={`mx-4 mt-3 flex items-center gap-2 rounded-pill px-4 py-2 text-xs font-semibold lg:mx-8 ${
        offline ? "bg-ink text-white" : "bg-teal-soft text-teal"
      }`}
    >
      <span
        className={`h-2 w-2 rounded-full ${offline ? "bg-sandstone" : "bg-teal"}`}
        aria-hidden
      />
      {offline
        ? "Offline — showing recently loaded data. New logs will need a connection."
        : "Back online."}
    </div>
  );
}
