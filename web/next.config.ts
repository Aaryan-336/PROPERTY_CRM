import type { NextConfig } from "next";

/**
 * A build stamp the service worker keys its caches on.
 *
 * Fixed at build time, so it is stable across every request of a deployment
 * and changes on the next one. Without it `sw.js` used a hardcoded version and
 * its activate handler — which deletes caches not matching the current version
 * — could never evict anything, so a returning user kept being served the
 * previous build's chunks.
 */
const buildId = process.env.VERCEL_GIT_COMMIT_SHA ?? String(Date.now());

const nextConfig: NextConfig = {
  env: {
    NEXT_PUBLIC_SW_VERSION: buildId,
  },
};

export default nextConfig;
