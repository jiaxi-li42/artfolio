export type ArticleImage = {
  id: string;
  position: number;
  src: string;
  preview: string;
  width: number;
  height: number;
  caption: string;
  alt: string;
  frames: number;
  previewWidth?: number;
};

export type ArticleSummary = {
  id: string;
  slug: string;
  batchDate: string;
  source: string;
  sourceLabel: string;
  title: string;
  cover: ArticleImage & { thumbnail: string };
  detailUrl: string;
};

export type ArticleDetail = {
  id: string;
  title: string;
  subtitle: string | null;
  sourceLabel: string;
  originalUrl: string;
  batchDate: string;
  publishedAt: string | null;
  fetchedAt: string;
  images: ArticleImage[];
  bodyParagraphs: string[];
  credits: { label: string; text: string; links?: { label: string; url: string }[] }[];
};

export type Catalog = {
  fetchedAt: string | null;
  batchDates: string[];
  articles: ArticleSummary[];
};
