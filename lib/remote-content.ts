import { createHash } from "node:crypto";

export const isContentVersion = (value: string) => /^[a-f0-9]{64}$/.test(value);

export function contentBaseUrl() {
  const value = process.env.ARTFOLIO_CONTENT_BASE_URL;
  if (!value) return null;
  const url = new URL(value.endsWith("/") ? value : `${value}/`);
  if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash) {
    throw new Error("ARTFOLIO_CONTENT_BASE_URL must be a plain HTTPS URL");
  }
  return url;
}

export async function readRemoteContent(key: string, checksum?: string): Promise<unknown> {
  const base = contentBaseUrl();
  if (!base) throw new Error("External content is not configured");
  for (let attempt = 0; attempt < 2; attempt++) {
    let canRetry = true;
    try {
      const response = await fetch(new URL(key, base), {
        cache: "no-store", redirect: "error", signal: AbortSignal.timeout(8000),
      });
      if (!response.ok || !response.body) {
        canRetry = (response.status >= 500 || [408, 429].includes(response.status)) && !response.headers.has("Retry-After");
        await response.body?.cancel();
        throw new Error(`Content request failed: ${response.status}`);
      }
      const reader = response.body.getReader();
      const chunks: Uint8Array[] = [];
      let bytes = 0;
      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          bytes += value.length;
          if (bytes > 16000000) { canRetry = false; throw new Error("Content response exceeds its read limit"); }
          chunks.push(value);
        }
      } finally { await reader.cancel().catch(() => {}); }
      canRetry = false;
      const raw = Buffer.concat(chunks);
      if (checksum && createHash("sha256").update(raw).digest("hex") !== checksum) throw new Error("Content checksum mismatch");
      return JSON.parse(raw.toString("utf8"));
    } catch (error) {
      if (!canRetry || attempt === 1) throw error;
      await new Promise(resolve => setTimeout(resolve, 250));
    }
  }
  throw new Error("Content unavailable");
}
