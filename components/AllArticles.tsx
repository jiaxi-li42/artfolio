"use client";

import Link from "next/link";
import { useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ArchiveNavigation } from "./ArchiveTransition";
import MaterialIcon from "./MaterialIcon";
import { updatedLabel } from "../lib/dates";
import type { ArticleSummary } from "../lib/types";
import { articleMatches, articleSources, sourceOption } from "../lib/article-search";
import "./all-articles.css";

type ArticleGroup = {
  date: string;
  articles: Pick<ArticleSummary, "id" | "slug" | "title" | "source" | "sourceLabel">[];
};

type ArchivePosition = { query: string; source?: string; limit?: number; top: number; cards: Record<string, number> };

function updateScrollEdges(scroller: HTMLElement) {
  const card = scroller.parentElement!;
  card.dataset.atTop = String(scroller.scrollTop <= 1);
  card.dataset.atBottom = String(scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop <= 1);
}

export default function AllArticles({ groups, initialSearch, initialSource = "" }: { groups: ArticleGroup[]; initialSearch: string; initialSource?: string }) {
  const navigateArchive = useContext(ArchiveNavigation);
  const grid = useRef<HTMLDivElement>(null);
  const results = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const more = useRef<HTMLDivElement>(null);
  const animation = useRef<Animation | null>(null);
  const request = useRef(0);
  const enterAfterUpdate = useRef(false);
  const composing = useRef(false);
  const restorePosition = useRef<ArchivePosition | null>(null);
  const [query, setQuery] = useState(sourceOption(initialSource)?.label ?? initialSearch);
  const [source, setSource] = useState(sourceOption(initialSource)?.id ?? "");
  const [draft, setDraft] = useState(sourceOption(initialSource)?.label ?? initialSearch);
  const [limit, setLimit] = useState(24);
  const [showSources, setShowSources] = useState(false);
  const [filtering, setFiltering] = useState(false);
  const canClear = Boolean(query) && draft === query;
  const matchingGroups = useMemo(() => groups.map(group => ({ ...group,
    articles: group.articles.filter(article => articleMatches(article, query, source)),
  })).filter(group => group.articles.length), [groups, query, source]);
  const visibleGroups = useMemo(() => matchingGroups.slice(0, limit), [matchingGroups, limit]);
  const count = matchingGroups.reduce((total, group) => total + group.articles.length, 0);

  useEffect(() => {
    if (!more.current || limit >= matchingGroups.length) return;
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) setLimit(value => value + 24);
    }, { rootMargin: "600px" });
    observer.observe(more.current);
    return () => observer.disconnect();
  }, [limit, matchingGroups.length]);

  function stopAnimation() {
    if (!animation.current) return;
    animation.current.onfinish = null;
    animation.current.cancel();
    animation.current = null;
  }

  useLayoutEffect(() => {
    const restore = () => {
      request.current++;
      stopAnimation();
      enterAfterUpdate.current = false;
      results.current?.style.removeProperty("opacity");
      setFiltering(false);
      if (location.pathname !== "/all") return;
      const params = new URLSearchParams(location.search);
      const option = sourceOption(params.get("source") ?? "");
      const value = option?.label ?? params.get("search") ?? "";
      const nextSource = option?.id ?? "";
      const saved: ArchivePosition | undefined = window.history.state?.artfolioArchive;
      restorePosition.current = saved?.query === value && (saved.source ?? "") === nextSource ? saved : { query: value, source: nextSource, top: 0, cards: {} };
      setLimit(Math.min(groups.length || 24, Math.max(24, restorePosition.current.limit ?? 24)));
      setQuery(value);
      setDraft(value);
      setSource(nextSource);
      setShowSources(false);
    };
    restore();
    const reduced = matchMedia("(prefers-reduced-motion: reduce)");
    const reduce = () => { if (reduced.matches) animation.current?.finish(); };
    window.addEventListener("popstate", restore);
    reduced.addEventListener("change", reduce);
    return () => {
      request.current++;
      stopAnimation();
      results.current?.style.removeProperty("opacity");
      window.removeEventListener("popstate", restore);
      reduced.removeEventListener("change", reduce);
    };
  }, []);

  useLayoutEffect(() => {
    const element = grid.current;
    if (!element) return;
    const cards = [...element.querySelectorAll<HTMLElement>(".date-card")];
    const updateEdges = () => {
      element.dataset.ready = "true";
      for (const card of cards) {
        updateScrollEdges(card.querySelector<HTMLElement>(".date-card-inner")!);
      }
    };
    updateEdges();
    const frame = requestAnimationFrame(() => {
      const saved = restorePosition.current;
      if (!saved || saved.query !== query) return;
      for (const card of cards) {
        const scroller = card.querySelector<HTMLElement>(".date-card-inner")!;
        scroller.scrollTop = saved.cards[card.dataset.batchDate!] ?? 0;
        updateScrollEdges(scroller);
      }
      window.scrollTo({ top: saved.top, behavior: "instant" });
      restorePosition.current = null;
    });
    const observer = new ResizeObserver(updateEdges);
    cards.forEach(card => observer.observe(card));
    let active = true;
    document.fonts.ready.then(() => { if (active) updateEdges(); });
    return () => { active = false; cancelAnimationFrame(frame); observer.disconnect(); };
  }, [visibleGroups, query, source]);

  useLayoutEffect(() => {
    if (!enterAfterUpdate.current || !results.current) return;
    enterAfterUpdate.current = false;
    const element = results.current;
    const incoming = element.animate([{ opacity: 0 }, { opacity: 1 }], {
      duration: matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 300, easing: "ease", fill: "forwards",
    });
    animation.current = incoming;
    incoming.onfinish = () => {
      element.style.removeProperty("opacity");
      incoming.cancel();
      if (animation.current === incoming) animation.current = null;
      setFiltering(false);
    };
    return () => { incoming.onfinish = null; incoming.cancel(); };
  }, [query, source]);

  async function search(value: string, nextSource = "") {
    const next = value.trim().replace(/\s+/g, " ");
    const element = results.current;
    const opacity = element ? getComputedStyle(element).opacity : "1";
    const token = ++request.current;
    stopAnimation();
    setDraft(next);
    setShowSources(false);
    if (next === query && nextSource === source) { element?.style.removeProperty("opacity"); setFiltering(false); return; }
    setFiltering(true);
    if (element && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const outgoing = element.animate([{ opacity }, { opacity: 0 }], { duration: 300, easing: "ease", fill: "forwards" });
      animation.current = outgoing;
      try { await outgoing.finished; } catch { return; }
    }
    if (token !== request.current) return;
    if (element) element.style.opacity = "0";
    stopAnimation();
    const url = new URL(location.href);
    if (next && !nextSource) url.searchParams.set("search", next); else url.searchParams.delete("search");
    if (nextSource) url.searchParams.set("source", nextSource); else url.searchParams.delete("source");
    const position: ArchivePosition = { query: next, source: nextSource, limit: 24, top: 0, cards: {} };
    window.history.replaceState({ ...window.history.state, artfolioArchive: position }, "", `${url.pathname}${url.search}${url.hash}`);
    restorePosition.current = position;
    enterAfterUpdate.current = true;
    setLimit(24);
    setSource(nextSource);
    setQuery(next);
  }

  function clearSearch() {
    void search("");
    input.current?.focus({ preventScroll: true });
  }

  function leave(href: string) {
    const cards = Object.fromEntries([...grid.current!.querySelectorAll<HTMLElement>(".date-card")].map(card => [
      card.dataset.batchDate!, card.querySelector<HTMLElement>(".date-card-inner")!.scrollTop,
    ]));
    window.history.replaceState({ ...window.history.state, artfolioArchive: { query, source, limit, top: scrollY, cards } }, "", location.href);
    navigateArchive(href);
  }

  return <main className="all-articles" data-route-ready="true" aria-labelledby="all-articles-heading">
    <h1 id="all-articles-heading" className="sr-only" tabIndex={-1}>All articles</h1>
    <header className="all-toolbar" aria-label="Article archive toolbar">
      <div className="all-toolbar-inner">
        <div className="all-search" onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setShowSources(false); }}>
          <form role="search" onSubmit={event => { event.preventDefault(); if (!composing.current) void search(draft); }}>
            <input ref={input} type="text" placeholder="I want to see..." aria-label="Search articles" value={draft}
              onFocus={() => setShowSources(true)} onClick={() => { if (!draft.trim()) setShowSources(true); }}
              onChange={event => { setDraft(event.target.value); if (!composing.current && !event.target.value.trim()) { void search(""); setShowSources(true); } }}
              onCompositionStart={() => { composing.current = true; }} onCompositionEnd={event => {
                composing.current = false;
                if (!event.currentTarget.value.trim()) { void search(""); setShowSources(true); }
              }}
              onKeyDown={event => {
                if (event.key === "Enter" && composing.current) event.preventDefault();
                if (event.key === "Escape" && !composing.current) { event.preventDefault(); void search(""); setShowSources(false); }
              }} />
            <button type={canClear ? "button" : "submit"} className="all-search-arrow" aria-label={canClear ? "Clear search" : "Submit search"} onClick={canClear ? clearSearch : undefined}>
              <MaterialIcon name={canClear ? "undo" : "arrow_forward"} />
            </button>
          </form>
          {showSources && !draft.trim() && <div className="all-source-shortcuts" role="group" aria-label="Filter by source">
            {[{ id: "", label: "All" }, ...articleSources].map(option => <button key={option.id} type="button" onClick={() => { input.current?.focus({ preventScroll: true }); void search(option.id ? option.label : "", option.id); }}><span>{option.label}</span></button>)}
          </div>}
        </div>
        <Link href="/" className="all-close" aria-label="Close all articles" onNavigate={event => { event.preventDefault(); leave("/"); }}>
          <MaterialIcon name="close" />
        </Link>
      </div>
    </header>
    <p className="sr-only" role="status">{filtering ? "Searching articles" : `${count} ${count === 1 ? "article" : "articles"} found`}</p>
    <div className="all-results" ref={results} aria-busy={filtering} inert={filtering}>
      {!count && <section className="all-no-results" aria-labelledby="no-articles-heading">
        <h2 id="no-articles-heading">{groups.length ? "No articles found" : "No articles yet"}</h2>
        <p>{groups.length ? "Your search returned no results. Try another search." : "Articles will appear here when content is added."}</p>
        {!!groups.length && <button type="button" className="show-all" onClick={clearSearch}>Clear search</button>}
      </section>}
      <div className="all-date-grid" ref={grid}>
      {visibleGroups.map(group => <section className="date-card" key={group.date} data-batch-date={group.date} data-at-top="true" data-at-bottom="true" aria-labelledby={`date-${group.date}`}>
        <div className="date-card-inner" onScroll={event => updateScrollEdges(event.currentTarget)}>
          <h2 id={`date-${group.date}`}><time dateTime={group.date}>{updatedLabel(`${group.date}T12:00:00Z`)}</time></h2>
          <div className="date-articles">
            {group.articles.map(article => <Link className="all-article" href={`/${article.slug}?from=all`} key={article.id} data-article-id={article.id} aria-label={`${article.sourceLabel}: ${article.title}`} onNavigate={event => { event.preventDefault(); leave(`/${article.slug}?from=all`); }}>
              <div className="all-article-header"><h3>{article.sourceLabel}</h3><p>{article.title}</p></div>
            </Link>)}
          </div>
        </div>
      </section>)}
      </div>
      {limit < matchingGroups.length && <div className="archive-more" ref={more}><button className="show-all" type="button" onClick={() => setLimit(value => value + 24)}>Load more dates</button></div>}
    </div>
  </main>;
}
