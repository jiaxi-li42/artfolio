import type { Metadata } from "next";
import AllArticles from "../../components/AllArticles";
import { readCatalog } from "../../lib/catalog";
import type { ArticleSummary } from "../../lib/types";
import { sourceOption } from "../../lib/article-search";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "All Articles | ARTFOLIO" };

export default async function AllArticlesPage({ searchParams }: { searchParams: Promise<{ search?: string; source?: string }> }) {
  const { search, source } = await searchParams;
  const catalog = await readCatalog();
  const dates = new Map<string, Pick<ArticleSummary, "id" | "slug" | "title" | "source" | "sourceLabel">[]>();
  for (const { id, slug, title, source: articleSource, sourceLabel, batchDate } of catalog.articles) {
    if (!dates.has(batchDate)) dates.set(batchDate, []);
    dates.get(batchDate)!.push({ id, slug, title, source: articleSource, sourceLabel });
  }
  const groups = [...dates].sort(([a], [b]) => b.localeCompare(a)).map(([date, articles]) => ({ date, articles }));
  return <AllArticles groups={groups} initialSearch={typeof search === "string" ? search : ""} initialSource={typeof source === "string" ? sourceOption(source)?.id : ""} />;
}
