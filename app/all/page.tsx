import type { Metadata } from "next";
import AllArticles from "../../components/AllArticles";
import { readCatalog } from "../../lib/catalog";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "All Articles | ARTFOLIO" };

export default async function AllArticlesPage({ searchParams }: { searchParams: Promise<{ search?: string }> }) {
  const { search } = await searchParams;
  const catalog = await readCatalog();
  const groups = [...catalog.batchDates].sort().reverse().map(date => ({
    date,
    articles: catalog.articles.filter(article => article.batchDate === date)
      .map(({ id, slug, title, sourceLabel }) => ({ id, slug, title, sourceLabel })),
  })).filter(group => group.articles.length);
  return <AllArticles groups={groups} initialSearch={typeof search === "string" ? search : ""} />;
}
