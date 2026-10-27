"use client";

import { Component, useState } from "react";
import type { ArticleDetail, ArticleImage } from "../lib/types";
import ArticleImageMedia from "./ArticleImage";
import ImageGallery from "./ImageGallery";
import MaterialIcon from "./MaterialIcon";
import "./reader.css";
import ContentError from "./ContentError";

export class ReaderErrorBoundary extends Component<{ children: React.ReactNode; onRetry: () => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error) { console.error("Article rendering failed", error); }
  render() { return this.state.failed ? <ContentError onRetry={this.props.onRetry} /> : this.props.children; }
}

function ImageFigure({ image, first = false, onOpen }: { image: ArticleImage; first?: boolean; onOpen: () => void }) {
  return (
    <figure className="reader-figure" data-position={image.position} data-image-id={image.id}>
      <ArticleImageMedia image={image} first={first} onOpen={onOpen} />
    </figure>
  );
}

function httpUrl(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function CreditLink({ label, url, outward = false }: { label: string; url: string; outward?: boolean }) {
  const href = httpUrl(url);
  const labelUrl = httpUrl(`https://${label}`);
  const urlLabel = /^https?:\/\//i.test(label) || Boolean(labelUrl && href &&
    new URL(labelUrl).hostname.replace(/^www\./, "") === new URL(href).hostname.replace(/^www\./, ""));
  return href ? <a className={urlLabel ? "credit-url" : undefined} href={href} target="_blank" rel="noopener noreferrer">{outward ? <><span className="source-link-label">{label}</span><MaterialIcon name="arrow_outward" /></> : label}</a> : <>{label}</>;
}

function CreditContent({ text = "", links = [] }: { text?: string | null; links?: { label: string; url: string }[] }) {
  const content = text || "";
  const matches = links.map(link => ({ link, index: content.indexOf(link.label) }))
    .filter(match => match.link.label && match.index >= 0)
    .sort((a, b) => a.index - b.index || b.link.label.length - a.link.label.length);
  const parts = [];
  const used = new Set<string>();
  let cursor = 0;
  for (const { link, index } of matches) {
    if (index < cursor) continue;
    parts.push(content.slice(cursor, index), <CreditLink key={`${index}-${link.url}`} {...link} />);
    cursor = index + link.label.length;
    used.add(link.url);
  }
  parts.push(content.slice(cursor));
  return <>{content && <span>{parts}</span>}{links.filter(link => !used.has(link.url)).flatMap((link, index) => [index ? ", " : "", <CreditLink key={index} {...link} />])}</>;
}

function TeamCredits({ field }: { field: ArticleDetail["credits"][number] }) {
  const links = field.links || [];
  return <>
    {field.text.split("\n").filter(Boolean).map((line, index) => {
      const role = line.match(/^([^:]+):\s*(.*)$/);
      const value = role ? role[2] : line;
      return <p className="credit-role" key={index}>
        {role && <span className="credit-role-label">{role[1]}:</span>}
        <CreditContent text={value} links={links.filter(link => value.includes(link.label))} />
      </p>;
    })}
    <CreditContent links={links.filter(link => !field.text.includes(link.label))} />
  </>;
}

export default function ArticleReader({ article, onRead }: { article: ArticleDetail; onRead: () => void }) {
  const [galleryIndex, setGalleryIndex] = useState<number | null>(null);
  function openGallery(index: number) {
    onRead();
    setGalleryIndex(index);
  }
  function locateGalleryImage(index: number) {
    const figure = document.querySelector<HTMLElement>(`.reader-figure[data-image-id="${article.images[index].id}"]`);
    if (!figure) return;
    const gap = Math.max((window.innerHeight - figure.offsetHeight) / 2, 8);
    window.scrollTo({ top: window.scrollY + figure.getBoundingClientRect().top - gap, behavior: "instant" });
  }
  function closeGallery(index: number) {
    setGalleryIndex(null);
    requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(`.reader-figure[data-image-id="${article.images[index].id}"] button`)?.focus({ preventScroll: true }));
  }
  const first = article.images[0];
  const fields: { label: string; text?: string | null; links?: { label: string; url: string }[] }[] = [
    { label: "Title", text: article.title },
    { label: "Subtitle", text: article.subtitle },
    { label: "Published", text: article.publishedAt ? new Intl.DateTimeFormat("en-US", { timeZone: "Europe/London", month: "long", day: "numeric", year: "numeric" }).format(new Date(article.publishedAt)) : null },
    ...article.credits,
  ];

  return (
    <article className="article-reader" data-article-id={article.id}>
      <h1 id="reader-heading" className="reader-heading" tabIndex={-1}>{article.title}</h1>
      {first && <ImageFigure key={first.id} image={first} first onOpen={() => openGallery(0)} />}
      {article.images.length > 1 && <div className="reader-grid">
        {article.images.slice(1).map((image, index) => <ImageFigure key={image.id} image={image} onOpen={() => openGallery(index + 1)} />)}
      </div>}
      <div className="reader-footer">
        <section className="reader-about reader-card" aria-labelledby="reader-about-heading">
          <h2 id="reader-about-heading">About</h2>
          <div className="reader-about-text">{article.bodyParagraphs.length
            ? article.bodyParagraphs.map((paragraph, index) => <p key={index}>{paragraph}</p>)
            : <p>No content found.</p>}</div>
        </section>
        <div className="reader-metadata">
          <section className="reader-credits reader-card" aria-labelledby="reader-credits-heading">
          <h2 id="reader-credits-heading">Credits</h2>
          <dl>
            {fields.filter(field => field.text || field.links?.length).map((field, index) => (
              <div key={index}>
                <dt>{field.label}</dt>
                <dd>
                  {field.label === "Creative team" && field.text
                    ? <TeamCredits field={{ ...field, text: field.text }} />
                    : <CreditContent text={field.text} links={field.links} />}
                </dd>
              </div>
            ))}
          </dl>
          </section>
          <section className="reader-source reader-card" aria-labelledby="reader-source-heading">
            <h2 id="reader-source-heading">Source</h2>
            <CreditLink label={article.sourceLabel} url={article.originalUrl} outward />
          </section>
        </div>
      </div>
      <button type="button" className="reader-back-to-top reader-card" onClick={() => {
        document.querySelector<HTMLButtonElement>(".reading-collapse")?.focus({ preventScroll: true });
        window.scrollTo({ top: 0, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
      }}>Back to top</button>
      {galleryIndex !== null && <ImageGallery article={article} initialIndex={galleryIndex} onLocate={locateGalleryImage} onClose={closeGallery} />}
    </article>
  );
}
