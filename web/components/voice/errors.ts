/** Why a voice/API call failed, in words that say what to do about it. */
export function explainFailure(
  res: Response | null,
  body: { error?: { code?: string; message?: string } } | null,
  feature: string,
  fallback: string,
): string {
  if (!res) {
    return "The server did not answer in time. On the free plan it sleeps when idle — try again in a moment.";
  }
  // FastAPI's own 404 for a route it does not have, as opposed to our
  // "Contact not found." -- the API is running an older build.
  if (res.status === 404 && (!body?.error?.message || body.error.message === "Not Found")) {
    return `${feature} isn't on the server yet. The API needs to be redeployed with this update.`;
  }
  if (res.status === 504 || (res.status === 502 && !body?.error)) {
    return "The server took too long to answer. It may be waking up — try again in a moment.";
  }
  return body?.error?.message ?? fallback;
}

export const UPLOAD_TIMEOUT_MS = 90_000;
