"use client";

import { useEffect, useState } from "react";

/**
 * Install-to-home-screen, as an actual button.
 *
 * The manifest and service worker already made this installable, but only
 * through the browser's own menu — which on Android is buried and on iOS is a
 * Share-sheet item most people have never used. Staff who work from a phone all
 * day should not have to be told where that is.
 *
 * Three quite different situations behind one control:
 *
 *   - Chromium fires `beforeinstallprompt`, which can be saved and replayed
 *     from a click. That is the real install flow.
 *   - iOS Safari fires nothing and exposes no API. The only honest thing is to
 *     say where the Share-sheet item is.
 *   - Already installed, so there is nothing to offer and the button hides
 *     itself rather than lying.
 */

type InstallEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

export function InstallApp() {
  const [prompt, setPrompt] = useState<InstallEvent | null>(null);
  const [installed, setInstalled] = useState(false);
  const [showIosHelp, setShowIosHelp] = useState(false);
  const [isIos, setIsIos] = useState(false);

  useEffect(() => {
    // `display-mode: standalone` is the cross-browser signal; navigator.standalone
    // is the iOS-only one, and neither covers both.
    const standalone =
      window.matchMedia("(display-mode: standalone)").matches ||
      (window.navigator as { standalone?: boolean }).standalone === true;
    setInstalled(standalone);

    const ua = window.navigator.userAgent;
    setIsIos(/iPad|iPhone|iPod/.test(ua) && !/CriOS|FxiOS/.test(ua));

    function onBeforeInstall(event: Event) {
      // Chromium shows its own banner otherwise, at a moment of its choosing.
      event.preventDefault();
      setPrompt(event as InstallEvent);
    }
    function onInstalled() {
      setInstalled(true);
      setPrompt(null);
    }

    window.addEventListener("beforeinstallprompt", onBeforeInstall);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onBeforeInstall);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  async function install() {
    if (!prompt) return;
    await prompt.prompt();
    const { outcome } = await prompt.userChoice;
    // A saved prompt is single-use; the browser will fire a fresh one later if
    // it still wants to. Keeping a spent one gives a button that does nothing.
    setPrompt(null);
    if (outcome === "accepted") setInstalled(true);
  }

  if (installed) return null;

  // Nothing to offer: not iOS and no prompt captured. Rendering a button that
  // cannot install anything is worse than rendering none.
  if (!prompt && !isIos) return null;

  return (
    <div className="rounded-card border border-hairline bg-card p-4">
      <p className="text-sm font-semibold text-ink">Install the app</p>
      <p className="mt-1 text-xs leading-relaxed text-slate">
        Adds Balaji to your home screen — full screen, no address bar, and it
        opens straight to your work.
      </p>

      {prompt ? (
        <button
          type="button"
          onClick={install}
          className="tap mt-3 w-full rounded-pill bg-ink px-5 text-sm font-semibold text-white"
        >
          Add to home screen
        </button>
      ) : (
        <>
          <button
            type="button"
            onClick={() => setShowIosHelp((v) => !v)}
            aria-expanded={showIosHelp}
            className="tap mt-3 w-full rounded-pill border border-hairline bg-card px-5 text-sm font-semibold text-ink"
          >
            How to install on iPhone
          </button>
          {showIosHelp && (
            <ol className="mt-3 space-y-1.5 text-xs leading-relaxed text-slate">
              <li>
                1. Tap the <span className="font-semibold text-ink">Share</span>{" "}
                button at the bottom of Safari.
              </li>
              <li>
                2. Scroll down and choose{" "}
                <span className="font-semibold text-ink">Add to Home Screen</span>.
              </li>
              <li>
                3. Tap <span className="font-semibold text-ink">Add</span>.
              </li>
              <li className="pt-1 text-[11px]">
                Safari only — Chrome on iPhone cannot install web apps.
              </li>
            </ol>
          )}
        </>
      )}
    </div>
  );
}
