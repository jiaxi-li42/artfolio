import { contentBaseUrl, isContentVersion, readRemoteContent } from "../../../../lib/remote-content";
import { validateArticleDetail } from "../../../../lib/content-validation";

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const version = new URL(request.url).searchParams.get("version") ?? "";
  if (!/^[a-z0-9-]{1,100}$/.test(id) || !isContentVersion(version)) {
    return Response.json({ error: "Invalid article reference" }, { status: 400 });
  }
  if (!contentBaseUrl()) return Response.json({ error: "Article not found" }, { status: 404 });
  try {
    const detail = validateArticleDetail(await readRemoteContent(`articles/${id}/${version}.json`, version), id);
    return Response.json(detail, { headers: { "Cache-Control": "public, max-age=31536000, immutable" } });
  } catch (error) {
    console.error("Article content unavailable", error);
    return Response.json({ error: "Article temporarily unavailable" }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
