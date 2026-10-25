import type { ArticleDetail, ArticleImage, ArticleSummary, Catalog } from "./types";

type RecordValue = Record<string, unknown>;
const object = (value: unknown): value is RecordValue => Boolean(value && typeof value === "object" && !Array.isArray(value));
const text = (value: unknown, empty = false): value is string => typeof value === "string" && value.length <= 200000 && (empty || Boolean(value.trim()));
const positive = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) > 0;
const identifier = (value: unknown): value is string => typeof value === "string" && /^[a-z0-9-]{1,120}$/.test(value);

function url(value: unknown, local = false) {
  if (!text(value)) return false;
  if (local && /^\/(?!\/)/.test(value) && !value.includes("\\")) return true;
  try {
    const parsed = new URL(value);
    return ["https:", "http:"].includes(parsed.protocol) && !parsed.username && !parsed.password;
  } catch { return false; }
}

export function validDay(value: unknown): value is string {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
}

export function validTimestamp(value: unknown): value is string {
  return typeof value === "string" && validDay(value.slice(0, 10)) &&
    /T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
}

function validImage(value: unknown): value is ArticleImage {
  if (!object(value)) return false;
  return identifier(value.id) && positive(value.position) && positive(value.width) && positive(value.height) &&
    value.width * value.height <= 40000000 && positive(value.frames) && url(value.src, true) && url(value.preview, true) &&
    text(value.caption, true) && text(value.alt, true) &&
    (value.previewWidth === undefined || positive(value.previewWidth) && value.previewWidth <= value.width);
}

export function validateArticleDetail(value: unknown, id?: string): ArticleDetail {
  if (!object(value) || !identifier(value.id) || id !== undefined && value.id !== id || !text(value.title) ||
      !text(value.sourceLabel) || !url(value.originalUrl) || !validDay(value.batchDate) || !validTimestamp(value.fetchedAt) ||
      value.subtitle !== null && !text(value.subtitle, true) ||
      value.publishedAt !== null && !validDay(value.publishedAt) && !validTimestamp(value.publishedAt) ||
      !Array.isArray(value.images) || !value.images.length || value.images.length > 100 ||
      !value.images.every((image, index) => validImage(image) && image.position === index + 1) ||
      new Set(value.images.map(image => image.id)).size !== value.images.length ||
      !Array.isArray(value.bodyParagraphs) || value.bodyParagraphs.length > 10000 || !value.bodyParagraphs.every(paragraph => text(paragraph)) ||
      !Array.isArray(value.credits) || value.credits.length > 500 || !value.credits.every(credit => object(credit) &&
        text(credit.label) && text(credit.text, true) && (credit.links === undefined || Array.isArray(credit.links) && credit.links.length <= 500 &&
          credit.links.every(link => object(link) && text(link.label) && url(link.url))))) {
    throw new Error("Invalid article content");
  }
  return value as ArticleDetail;
}

export function validateCatalog(value: unknown): Catalog {
  if (!object(value) || value.fetchedAt !== null && !validTimestamp(value.fetchedAt) ||
      !Array.isArray(value.batchDates) || !value.batchDates.every(validDay) ||
      !Array.isArray(value.articles) || !value.articles.every(article => object(article) && identifier(article.id) &&
        text(article.slug) && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(article.slug) && !["all", "api", "about", "data", "media", "fonts", "brand"].includes(article.slug) &&
        text(article.title) && text(article.source) && text(article.sourceLabel) && validDay(article.batchDate) &&
        validImage(article.cover) && "thumbnail" in article.cover && url(article.cover.thumbnail, true) && typeof article.detailUrl === "string" &&
        /^\/(?:data\/articles\/[a-z0-9-]+\.json|api\/articles\/[a-z0-9-]+\?version=[a-f0-9]{64})$/.test(article.detailUrl))) {
    throw new Error("Invalid content catalog");
  }
  const articles = value.articles as ArticleSummary[];
  if (new Set(articles.map(article => article.id)).size !== articles.length || new Set(articles.map(article => article.slug)).size !== articles.length ||
      articles.some(article => !(value.batchDates as string[]).includes(article.batchDate))) throw new Error("Inconsistent content catalog");
  return value as Catalog;
}
