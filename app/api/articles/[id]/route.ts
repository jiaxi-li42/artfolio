import type { ArticleDetail } from "../../../../lib/types";
import { contentBaseUrl, isContentVersion, readRemoteContent } from "../../../../lib/remote-content";

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const version = new URL(request.url).searchParams.get("version") ?? "";
  if (!/^[a-z0-9-]{1,100}$/.test(id) || !isContentVersion(version)) {
    return Response.json({ error: "Invalid article reference" }, { status: 400 });
  }
  if (!contentBaseUrl()) return Response.json({ error: "Article not found" }, { status: 404 });
  try {
    const detail = await readRemoteContent(`articles/${id}/${version}.json`, version) as ArticleDetail;
    if (detail.id !== id || !detail.title || !Array.isArray(detail.images) || !detail.images.length ||
        !Array.isArray(detail.bodyParagraphs) || !Array.isArray(detail.credits)) {
      throw new Error("Invalid article detail");
    }
    return Response.json(detail, { headers: { "Cache-Control": "public, max-age=31536000, immutable" } });
  } catch (error) {
    console.error("Article content unavailable", error);
    return Response.json({ error: "Article temporarily unavailable" }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
