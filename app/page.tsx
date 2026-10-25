import { notFound } from "next/navigation";
import type { Metadata } from "next";
import Artfolio from "../components/Artfolio";
import { londonDate, parseBatchDate } from "../lib/dates";
import { readCatalog } from "../lib/catalog";

export const dynamic = "force-dynamic";

type PageProps = { params: Promise<{ slug?: string }>; searchParams: Promise<{ date?: string }> };

async function resolvePage({ params, searchParams }: PageProps) {
  const catalog = await readCatalog();
  const { slug } = await params;
  if (slug) {
    const first = catalog.articles.find(article => article.slug === slug);
    if (!first) notFound();
    return { catalog, first, slug, initialReading: true, emptyMessage: "" };
  }
  const { date } = await searchParams;
  const requested = typeof date === "string" ? parseBatchDate(date) : null;
  const invalid = date !== undefined && (!requested || requested > londonDate(new Date().toISOString()));
  const first = invalid ? undefined : catalog.articles.find(article => !requested || article.batchDate === requested);
  return { catalog, first, slug, initialReading: false, emptyMessage: invalid ? "Invalid date." : catalog.articles.length ? "No articles for this date." : "No articles yet." };
}

export async function generateMetadata(props: PageProps): Promise<Metadata> {
  const { first, slug } = await resolvePage(props);
  return { title: slug && first ? `${first.title} | ARTFOLIO` : "ARTFOLIO" };
}

export default async function Page(props: PageProps) {
  const { catalog, first, initialReading, emptyMessage } = await resolvePage(props);
  return <Artfolio catalog={catalog} initialId={first?.id ?? null} initialReading={initialReading} emptyMessage={emptyMessage} />;
}
