"use client";

import { useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { updatedLabel } from "../lib/dates";
import type { ArticleDetail, Catalog } from "../lib/types";
import ArticleReader, { ReaderErrorBoundary } from "./ArticleReader";
import { validateArticleDetail } from "../lib/content-validation";
import ContentError from "./ContentError";
import { ArchiveNavigation } from "./ArchiveTransition";
import { directoryLayout, directoryWindow, restoredDirectoryScroll } from "../lib/directory-window";

gsap.registerPlugin(ScrollTrigger);
let mountedDirectory = false;

export default function Artfolio({ catalog, initialId, initialReading, emptyMessage }: {
  catalog: Catalog; initialId: string | null; initialReading: boolean; emptyMessage: string;
}) {
  const navigateArchive = useContext(ArchiveNavigation);
  const nav = useRef<HTMLElement>(null);
  const detailCache = useRef(new Map<string, ArticleDetail>());
  const focusAfterLoad = useRef(false);
  const directoryScroll = useRef(0);
  const directoryStep = useRef(106);
  const directoryViewport = useRef({ width: 0, height: 0 });
  const directoryInput = useRef(false);
  const archiveDirectoryTarget = useRef<string | null>(null);
  const pendingDirectoryScroll = useRef<number | null>(null);
  const readingCard = useRef<HTMLDivElement>(null);
  const readingContent = useRef<HTMLDivElement>(null);
  const finishDesktop = useRef<(() => void) | null>(null);
  const finishMobile = useRef<(() => void) | null>(null);
  const restoringHistory = useRef(false);
  const navigationFrame = useRef(0);
  const openingCard = useRef<{ rect: DOMRect; opacity: number; background: string } | null>(null);
  const [readerPhase, setReaderPhase] = useState<"idle" | "opening" | "closing">("idle");
  const desktopTarget = useRef<string | null | undefined>(undefined);
  const [desktopPhase, setDesktopPhase] = useState<"idle" | "leaving" | "entering">("idle");
  const [selectedId, setSelectedId] = useState(initialId);
  const [detail, setDetail] = useState<ArticleDetail | null>(null);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [mobileReading, setMobileReading] = useState(initialReading);
  const [desktop, setDesktop] = useState(false);
  const [range, setRange] = useState(() => directoryWindow(0, catalog.articles.length));
  const [layout, setLayout] = useState({ step: 106, header: 311 });
  const step = layout.step;
  const visible = useMemo(() => catalog.articles.slice(range.start, range.end), [catalog.articles, range]);
  const selected = catalog.articles.find(article => article.id === selectedId);
  const desktopReady = desktopPhase === "entering";
  const shouldRead = desktop || mobileReading;

  function showDirectoryIndex(index: number) {
    const layout = directoryLayout(window.innerWidth, window.innerHeight);
    const next = directoryWindow(index, catalog.articles.length, layout.viewportRows);
    setRange(previous => previous.start === next.start && previous.end === next.end ? previous : next);
  }

  useLayoutEffect(() => {
    const previousRestoration = window.history.scrollRestoration;
    // ScrollTrigger also caches this policy and reapplies it when layouts refresh.
    ScrollTrigger.clearScrollMemory("manual");
    window.scrollTo({ top: 0, behavior: "instant" });
    nav.current?.scrollTo({ top: 0, behavior: "instant" });
    const url = new URL(window.location.href);
    const reload = !mountedDirectory && (performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined)?.type === "reload";
    mountedDirectory = true;
    if (initialId && url.searchParams.get("from") === "all") {
      archiveDirectoryTarget.current = initialId;
      showDirectoryIndex(catalog.articles.findIndex(article => article.id === initialId));
      url.searchParams.delete("from");
      window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
    } else {
      const saved = window.history.state?.artfolio;
      if (!reload && saved && (url.pathname === "/" || saved.id === initialId) && Number.isFinite(saved.scroll) && saved.scroll >= 0) {
        directoryScroll.current = restoredDirectoryScroll(saved, window.innerWidth, window.innerHeight);
        pendingDirectoryScroll.current = directoryScroll.current;
        const layout = directoryLayout(window.innerWidth, window.innerHeight);
        showDirectoryIndex(Math.floor(Math.max(0, directoryScroll.current - layout.header) / layout.step));
        if (url.pathname === "/" && window.innerWidth <= 656 && catalog.articles.some(article => article.id === saved.id)) setSelectedId(saved.id);
      }
    }
    return () => ScrollTrigger.clearScrollMemory(previousRestoration);
  }, []);

  useLayoutEffect(() => {
    const layout = directoryLayout(window.innerWidth, window.innerHeight);
    window.history.replaceState({ ...window.history.state, artfolio: { id: initialId, reading: initialReading, scroll: directoryScroll.current, step: layout.step, header: layout.header } }, "", window.location.href);
    const restore = (event: PopStateEvent) => {
      if (location.pathname === "/all") return;
      archiveDirectoryTarget.current = null;
      pendingDirectoryScroll.current = null;
      const entry = event.state?.artfolio;
      const fallback = catalog.articles.find(article => `/${article.slug}` === location.pathname) || catalog.articles[0];
      const home = location.pathname === "/" && !location.search;
      const id = home && window.innerWidth > 656 ? catalog.articles[0]?.id ?? null : entry?.id === null ? null : catalog.articles.find(article => article.id === entry?.id)?.id ?? fallback?.id ?? null;
      const reading = home ? false : typeof entry?.reading === "boolean" ? entry.reading : Boolean(id);
      restoringHistory.current = true;
      finishDesktop.current?.();
      finishMobile.current?.();
      setDesktopPhase("idle");
      setReaderPhase("idle");
      desktopTarget.current = undefined;
      cancelAnimationFrame(navigationFrame.current);
      setSelectedId(id);
      setDetail(null);
      setError(false);
      setMobileReading(reading);
      const article = catalog.articles.find(item => item.id === id);
      document.title = location.pathname !== "/" && article ? `${article.title} | ARTFOLIO` : "ARTFOLIO";
      focusAfterLoad.current = reading;
      directoryScroll.current = restoredDirectoryScroll(entry ?? {}, window.innerWidth, window.innerHeight);
      const layout = directoryLayout(window.innerWidth, window.innerHeight);
      showDirectoryIndex(Math.floor(Math.max(0, directoryScroll.current - layout.header) / layout.step));
      window.scrollTo({ top: 0, behavior: "instant" });
      navigationFrame.current = requestAnimationFrame(() => {
        ScrollTrigger.refresh();
        nav.current?.scrollTo({ top: directoryScroll.current, behavior: "instant" });
        ScrollTrigger.update();
        if (!reading) nav.current?.querySelector<HTMLAnchorElement>(`a[data-article-id="${id}"]`)?.focus({ preventScroll: true });
      });
      restoringHistory.current = false;
    };
    window.addEventListener("popstate", restore);
    return () => { window.removeEventListener("popstate", restore); cancelAnimationFrame(navigationFrame.current); };
  }, [catalog, initialId, initialReading]);

  useLayoutEffect(() => {
    const screen = matchMedia("(min-width: 657px)");
    const update = () => setDesktop(screen.matches);
    update();
    screen.addEventListener("change", update);
    return () => screen.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    document.title = location.pathname !== "/" && selected ? `${selected.title} | ARTFOLIO` : "ARTFOLIO";
  }, [selected, mobileReading]);

  useLayoutEffect(() => {
    const showHome = () => {
      if (window.innerWidth <= 656 || location.pathname !== "/" || location.search || readerPhase !== "idle" || desktopPhase !== "idle") return;
      const latestId = catalog.articles[0]?.id ?? null;
      if (selectedId !== latestId) { setSelectedId(latestId); setDetail(null); setError(false); setMobileReading(false); }
    };
    showHome();
    window.addEventListener("resize", showHome);
    return () => window.removeEventListener("resize", showHome);
  }, [catalog, selectedId, readerPhase, desktopPhase]);

  useLayoutEffect(() => {
    const element = nav.current;
    if (!element) return;
    const measure = () => {
      directoryInput.current = false;
      const { step, header } = directoryLayout(window.innerWidth, window.innerHeight);
      const previousHeader = parseFloat(element.style.getPropertyValue("--header-height")) || 311;
      const scroll = pendingDirectoryScroll.current ?? directoryScroll.current;
      if (directoryViewport.current.width && !archiveDirectoryTarget.current && scroll > previousHeader && (directoryStep.current !== step || header !== previousHeader || Math.abs(element.scrollTop - scroll) > 1)) {
        const index = (scroll - previousHeader) / directoryStep.current;
        directoryScroll.current = header + index * step;
        pendingDirectoryScroll.current = directoryScroll.current;
        showDirectoryIndex(Math.floor(index));
      }
      directoryStep.current = step;
      directoryViewport.current = { width: window.innerWidth, height: window.innerHeight };
      setLayout({ step, header });
      element.style.setProperty("--header-height", `${header}px`);
      updateRange();
    };
    const updateRange = () => {
      if (archiveDirectoryTarget.current || pendingDirectoryScroll.current !== null || !element.clientHeight || directoryViewport.current.width !== window.innerWidth || directoryViewport.current.height !== window.innerHeight) return;
      const header = element.querySelector<HTMLElement>(".nav-header")?.offsetHeight ?? 311;
      if (directoryInput.current) directoryScroll.current = element.scrollTop;
      showDirectoryIndex(Math.floor(Math.max(0, element.scrollTop - header) / (window.innerWidth <= 768 ? 86 : 106)));
      if (directoryInput.current && location.pathname !== "/all" && window.history.state?.artfolio) window.history.replaceState({ ...window.history.state,
        artfolio: { ...window.history.state.artfolio, scroll: directoryScroll.current, step: directoryStep.current, header },
      }, "", location.href);
    };
    measure();
    const userScroll = () => { directoryInput.current = true; };
    window.addEventListener("resize", measure);
    element.addEventListener("scroll", updateRange, { passive: true });
    element.addEventListener("wheel", userScroll, { passive: true });
    element.addEventListener("touchstart", userScroll, { passive: true });
    element.addEventListener("keydown", userScroll);
    return () => {
      window.removeEventListener("resize", measure); element.removeEventListener("scroll", updateRange);
      element.removeEventListener("wheel", userScroll); element.removeEventListener("touchstart", userScroll); element.removeEventListener("keydown", userScroll);
    };
  }, [catalog.articles.length]);

  useLayoutEffect(() => {
    const element = nav.current;
    if (!element?.clientHeight) return;
    const media = gsap.matchMedia();
    media.add({ motion: "(prefers-reduced-motion: no-preference)", small: "(max-width: 768px)" }, context => {
      if (!context.conditions?.motion) return;
      const cards = [...element.querySelectorAll<HTMLElement>(".nav-card")];
      cards.forEach((card, index) => {
        const inner = card.querySelector<HTMLElement>(".article-card")!;
        const shade = card.querySelector<HTMLElement>(".card-shade")!;
        const height = card.offsetHeight;
        const gap = parseFloat(getComputedStyle(card.parentElement!).rowGap);
        const timeline = gsap.timeline()
          .set(inner, { opacity: 0, scale: 0.5, y: -(height + gap) * 2, transformOrigin: "50% 100%" })
          .set(shade, { opacity: 0 })
          .to(inner, { opacity: 1, duration: 0.3, ease: "none" }, 0)
          .to(inner, { y: 0, scale: 1, duration: 1, ease: "none" }, 0);
        if (index < cards.length - 1) timeline.to(shade, { opacity: 1, duration: 0.5, ease: "none" }, 0.5);
        ScrollTrigger.create({ scroller: element, trigger: card, animation: timeline, scrub: true,
          start: () => `top-=${(height + gap) * 2} bottom-=${height}`,
          end: () => `bottom bottom-=${height / 2}`, invalidateOnRefresh: true });
        if (index < cards.length - 1) {
          const background = gsap.timeline().set(shade, { opacity: 1 }).to(shade, { opacity: 0, duration: 1, ease: "none" });
          ScrollTrigger.create({ scroller: element, trigger: card, animation: background, scrub: true,
            start: () => `bottom bottom-=${height * 0.8}`, end: () => `bottom bottom-=${height * 1.5}` });
        }
      });
    }, element);
    const refresh = () => {
      ScrollTrigger.refresh(); alignArchiveDirectory();
      if (pendingDirectoryScroll.current !== null && element.clientHeight) {
        element.scrollTop = pendingDirectoryScroll.current;
        directoryScroll.current = element.scrollTop;
        pendingDirectoryScroll.current = null;
        ScrollTrigger.update();
      }
    };
    const frame = requestAnimationFrame(refresh);
    const observer = archiveDirectoryTarget.current || pendingDirectoryScroll.current !== null ? new ResizeObserver(() => {
      if ((archiveDirectoryTarget.current || pendingDirectoryScroll.current !== null) && element.clientHeight) refresh();
    }) : null;
    observer?.observe(element);
    return () => { cancelAnimationFrame(frame); observer?.disconnect(); media.revert(); };
  }, [visible, layout, desktop, mobileReading, readerPhase]);

  useEffect(() => {
    if (!selected || !shouldRead) return;
    const cached = detailCache.current.get(selected.detailUrl);
    if (cached) {
      detailCache.current.delete(selected.detailUrl);
      detailCache.current.set(selected.detailUrl, cached);
      setDetail(cached); setError(false); return;
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => { setError(true); controller.abort(); }, 20000);
    setError(false);
    fetch(selected.detailUrl, { signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error("Article unavailable"); return response.json(); })
      .then((value: unknown) => {
        const article = validateArticleDetail(value, selected.id);
        if (!controller.signal.aborted) {
          detailCache.current.delete(selected.detailUrl);
          detailCache.current.set(selected.detailUrl, article);
          if (detailCache.current.size > 8) detailCache.current.delete(detailCache.current.keys().next().value!);
          setDetail(article);
        }
      })
      .catch(() => { if (!controller.signal.aborted) setError(true); })
      .finally(() => clearTimeout(timeout));
    return () => { clearTimeout(timeout); controller.abort(); };
  }, [selected, retry, shouldRead]);

  useEffect(() => {
    if (!detail || !focusAfterLoad.current || readerPhase !== "idle" || desktopPhase !== "idle") return;
    const frame = requestAnimationFrame(() => {
      document.getElementById("reader-heading")?.focus({ preventScroll: true });
      focusAfterLoad.current = false;
    });
    return () => cancelAnimationFrame(frame);
  }, [detail, mobileReading, readerPhase, desktopPhase]);

  useLayoutEffect(() => {
    const content = readingContent.current;
    if (desktopPhase === "idle" || !content) return;
    let animation: Animation | undefined;
    let finished = false, preserveOpacity = true;
    const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
    const complete = () => {
      if (finished) return;
      finished = true;
      preserveOpacity = false;
      animation?.cancel();
      content.style.removeProperty("opacity");
      if (desktopPhase === "leaving") commitDesktopSelection();
      desktopTarget.current = undefined;
      setDesktopPhase("idle");
    };
    const reduce = () => { if (reducedMotion.matches) complete(); };
    const width = window.innerWidth;
    const resize = () => { if (window.innerWidth !== width) complete(); };
    finishDesktop.current = complete;
    window.addEventListener("resize", resize);
    reducedMotion.addEventListener("change", reduce);

    if (desktopPhase === "leaving") {
      animation = content.animate([{ opacity: getComputedStyle(content).opacity }, { opacity: 0 }], { duration: 300, easing: "ease", fill: "forwards" });
      animation.onfinish = () => {
        if (finished) return;
        finished = true;
        content.style.opacity = "0";
        animation?.cancel();
        commitDesktopSelection();
        setDesktopPhase("entering");
      };
    } else if (desktopReady) {
      animation = content.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 300, easing: "ease", fill: "forwards" });
      animation.onfinish = complete;
    }
    return () => {
      // Retargeting a partially entered article starts its exit at the visible opacity.
      const opacity = getComputedStyle(content).opacity;
      animation?.cancel();
      if (preserveOpacity) content.style.opacity = opacity;
      else content.style.removeProperty("opacity");
      window.removeEventListener("resize", resize);
      reducedMotion.removeEventListener("change", reduce);
      if (finishDesktop.current === complete) finishDesktop.current = null;
    };
  }, [desktopPhase, desktopReady]);

  useLayoutEffect(() => {
    if (readerPhase === "idle") return;
    const card = readingCard.current, content = readingContent.current, directory = nav.current;
    const source = directory?.querySelector<HTMLAnchorElement>(`a[data-article-id="${selectedId}"]`);
    if (!card || !content || !directory || !source) { if (readerPhase === "closing") restoreDirectory(); setReaderPhase("idle"); return; }
    const previousOverflow = document.documentElement.style.overflow;
    const previousVisibility = source.style.visibility;
    const collapse = card.querySelector("button")!;
    const timeline = gsap.timeline();
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      timeline.kill();
      if (readerPhase === "closing") restoreDirectory();
      setReaderPhase("idle");
    };
    const width = window.innerWidth;
    // iOS browser toolbars resize the height while scrolling; let the animation continue.
    const resize = () => { if (window.innerWidth !== width) finish(); };
    const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
    const reduce = () => { if (reducedMotion.matches) finish(); };
    finishMobile.current = finish;
    document.documentElement.style.overflow = "hidden";
    window.addEventListener("resize", resize);
    reducedMotion.addEventListener("change", reduce);
    source.style.visibility = "hidden";
    const target = card.getBoundingClientRect();
    const height = Math.min(content.scrollHeight, Math.max(1, window.innerHeight - target.bottom - 16));
    gsap.set(content, { height, overflow: "hidden", willChange: "clip-path, transform, opacity" });
    gsap.set(card, { transformOrigin: "top left", willChange: "transform, opacity" });

    if (readerPhase === "opening" && openingCard.current) {
      const origin = openingCard.current;
      const background = getComputedStyle(card).backgroundColor;
      gsap.set(card, { x: origin.rect.left - target.left, y: origin.rect.top - target.top, scaleX: origin.rect.width / target.width, scaleY: origin.rect.height / target.height, opacity: origin.opacity, backgroundColor: origin.background });
      gsap.set(content, { clipPath: "inset(0% 0% 100% 0%)", opacity: 0 });
      gsap.set(collapse, { opacity: 0 });
      timeline.to(directory, { opacity: 0, duration: .18 }, 0)
        .to(card, { x: 0, y: 0, scaleX: 1, scaleY: 1, opacity: 1, backgroundColor: background, duration: .42, ease: "power3.inOut" }, 0)
        .to(collapse, { opacity: 1, duration: .16 }, .42)
        .to(content, { clipPath: "inset(0% 0% 0% 0%)", opacity: 1, duration: .46, ease: "power2.out" }, .42)
        .call(finish);
    } else {
      gsap.set(directory, { opacity: 0 });
      ScrollTrigger.refresh();
      alignArchiveDirectory();
      directory.scrollTop = directoryScroll.current;
      ScrollTrigger.update();
      const destination = source.getBoundingClientRect();
      timeline.to(collapse, { opacity: 0, duration: .12 }, 0)
        .to(content, { clipPath: "inset(0% 0% 100% 0%)", opacity: 0, duration: .34, ease: "power2.in" }, 0)
        .to(card, { x: destination.left - target.left, y: destination.top - target.top, scaleX: destination.width / target.width, scaleY: destination.height / target.height, backgroundColor: getComputedStyle(source).backgroundColor, duration: .42, ease: "power3.inOut" }, .34)
        .to(directory, { opacity: 1, duration: .24 }, .34)
        .call(finish);
    }
    return () => {
      timeline.kill();
      window.removeEventListener("resize", resize);
      reducedMotion.removeEventListener("change", reduce);
      document.documentElement.style.overflow = previousOverflow;
      source.style.visibility = previousVisibility;
      gsap.set(directory, { clearProps: "opacity" });
      gsap.set(card, { clearProps: "transform,transformOrigin,opacity,backgroundColor,willChange" });
      gsap.set(content, { clearProps: "height,overflow,clipPath,transform,opacity,willChange" });
      gsap.set(collapse, { clearProps: "opacity" });
      openingCard.current = null;
      if (finishMobile.current === finish) finishMobile.current = null;
    };
  }, [readerPhase]);

  function select(id: string) {
    if (readerPhase !== "idle") return;
    directoryInput.current = false;
    cancelAnimationFrame(navigationFrame.current);
    if (window.innerWidth > 656) {
      if (id !== selectedId || desktopPhase !== "idle") {
        directoryScroll.current = nav.current?.scrollTop ?? 0;
        transitionDesktop(id);
      } else updateHistory(id, true);
      return;
    }
    const openingMobile = window.innerWidth <= 656 && !mobileReading;
    if (id === selectedId && !openingMobile) return;
    directoryScroll.current = nav.current?.scrollTop ?? 0;
    const source = nav.current?.querySelector<HTMLAnchorElement>(`a[data-article-id="${id}"]`);
    if (openingMobile && source && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const css = getComputedStyle(source);
      openingCard.current = { rect: source.getBoundingClientRect(), opacity: Number(css.opacity), background: css.backgroundColor };
      setReaderPhase("opening");
    }
    focusAfterLoad.current = true;
    if (id !== selectedId) { setDetail(null); setError(false); setSelectedId(id); }
    setMobileReading(true);
    updateHistory(id, true);
    window.scrollTo({ top: 0, behavior: "instant" });
  }

  function alignArchiveDirectory() {
    const directory = nav.current, id = archiveDirectoryTarget.current;
    if (!directory?.clientHeight || !id) return;
    const row = directory.querySelector<HTMLElement>(`a[data-article-id="${id}"]`)?.parentElement;
    if (!row) return;
    directory.scrollTop = row.offsetTop - parseFloat(getComputedStyle(directory).paddingTop);
    directoryScroll.current = directory.scrollTop;
    archiveDirectoryTarget.current = null;
    ScrollTrigger.update();
    const layout = directoryLayout(window.innerWidth, window.innerHeight);
    window.history.replaceState({ ...window.history.state, artfolio: { ...window.history.state?.artfolio, scroll: directoryScroll.current, step: layout.step, header: layout.header } }, "", window.location.href);
  }

  function commitDesktopSelection() {
    const target = desktopTarget.current;
    if (target === undefined) return;
    const id = target === null ? catalog.articles[0]?.id ?? null : target;
    const reading = target !== null && id !== null;
    focusAfterLoad.current = reading;
    if (id !== selectedId) { setDetail(null); setError(false); setSelectedId(id); }
    setMobileReading(reading);
    updateHistory(id, reading);
    window.scrollTo({ top: 0, behavior: "instant" });
    if (target === null) document.querySelector<HTMLAnchorElement>(".brand-home")?.focus({ preventScroll: true });
  }

  function transitionDesktop(id: string | null) {
    desktopTarget.current = id;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      commitDesktopSelection();
      desktopTarget.current = undefined;
      setDesktopPhase("idle");
      return;
    }
    setDesktopPhase("leaving");
  }

  function back() {
    if (readerPhase !== "idle") return;
    window.scrollTo({ top: 0, behavior: "instant" });
    if (window.innerWidth <= 656 && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setReaderPhase("closing");
      return;
    }
    restoreDirectory();
  }

  function restoreDirectory() {
    focusAfterLoad.current = false;
    setMobileReading(false);
    updateHistory(selectedId, false);
    window.scrollTo({ top: 0, behavior: "instant" });
    cancelAnimationFrame(navigationFrame.current);
    navigationFrame.current = requestAnimationFrame(() => {
      ScrollTrigger.refresh();
      alignArchiveDirectory();
      nav.current?.scrollTo({ top: directoryScroll.current, behavior: "instant" });
      ScrollTrigger.update();
      nav.current?.querySelector<HTMLAnchorElement>(`a[data-article-id="${selectedId}"]`)?.focus({ preventScroll: true });
    });
  }

  function updateHistory(id: string | null, reading: boolean) {
    if (restoringHistory.current) return;
    const article = catalog.articles.find(item => item.id === id);
    const url = reading && article ? `/${article.slug}` : "/";
    const current = window.history.state?.artfolio;
    if (location.pathname === url && !location.search && current?.id === id && current?.reading === reading) return;
    const layout = directoryLayout(window.innerWidth, window.innerHeight);
    window.history.pushState({ artfolio: { id, reading, scroll: directoryScroll.current, step: layout.step, header: layout.header } }, "", url);
    document.title = reading && article ? `${article.title} | ARTFOLIO` : "ARTFOLIO";
  }

  const phase = desktopPhase === "idle" ? readerPhase : desktopPhase === "leaving" ? "closing" : "opening";
  return <div className="artfolio" data-route-ready="true" data-page-mode={mobileReading ? "reading" : "directory"} data-reader-phase={phase} data-desktop-phase={desktopPhase}>
    <a className="skip-link" href="#reading-area">Skip to article</a>
    <aside className="article-nav" ref={nav} aria-label="Article directory" inert={readerPhase !== "idle"}>
      <header className="nav-header">
        <Link className="show-all" href="/all" onNavigate={event => { event.preventDefault(); navigateArchive("/all"); }}>Show all articles</Link>
        <div className="identity">
          <a className="brand-home" href="/" aria-label="ARTFOLIO home" onClick={event => {
            if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            if (window.innerWidth > 656 && initialId) {
              event.preventDefault();
              if (selected || desktopPhase !== "idle") transitionDesktop(null);
            }
          }}><img className="wordmark" src="/brand/artfolio-logo.svg" alt="ARTFOLIO" width="115" height="17" /></a>
          <p className="last-updated">Last Updated on<br />{catalog.fetchedAt ? <time dateTime={catalog.fetchedAt}>{updatedLabel(catalog.fetchedAt)}</time> : <span>Not updated yet</span>}</p>
        </div>
      </header>
      {!selected && !initialId && <p className="mobile-empty empty-state" role="status">{emptyMessage}</p>}
      <nav className="article-cards" aria-label="Articles, newest batch first" style={{ paddingTop: range.start * step, paddingBottom: (catalog.articles.length - range.end) * step }}>
        {visible.map((article, index) => <div className="nav-card" key={article.id} style={{ zIndex: catalog.articles.length - range.start - index }}>
          <a className="article-card" href={`/${article.slug}`} data-article-id={article.id}
            aria-current={selectedId === article.id ? "true" : undefined}
            aria-label={`${article.sourceLabel}: ${article.title}`} onClick={event => {
              if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
              event.preventDefault(); select(article.id);
            }}>
            <span className="card-shade" aria-hidden="true" />
            <span className="card-image"><img src={article.cover.thumbnail} alt="" width="65" height="65" loading={range.start === 0 && index < 6 ? "eager" : "lazy"} /></span>
            <span className="card-copy"><span className="card-source">{article.sourceLabel}</span><span className="card-title">{article.title}</span></span>
          </a>
        </div>)}
      </nav>
      <div className="directory-sentinel" aria-hidden="true" />
    </aside>
    <main className="reading-area" id="reading-area" aria-label="Selected article" aria-busy={phase !== "idle" || Boolean(selected && !detail && !error)} inert={phase !== "idle"}>
      {selected && <div className="reading-card" ref={readingCard}>
        <span className="card-image"><img src={selected.cover.thumbnail} alt="" width="56" height="56" /></span>
        <span className="card-copy"><span className="card-source">{selected.sourceLabel}</span><span className="card-title">{selected.title}</span></span>
        <button className="reading-collapse" type="button" onClick={back}>Collapse</button>
      </div>}
      <div className="reading-content" ref={readingContent}>
        {!shouldRead ? null : !selected ? !initialId && <p className="empty-state">{emptyMessage}</p> : error ? <ContentError onRetry={() => { detailCache.current.delete(selected.detailUrl); setRetry(value => value + 1); }} /> : detail ? <ReaderErrorBoundary key={`${detail.id}:${retry}`} onRetry={() => { detailCache.current.delete(selected.detailUrl); setDetail(null); setRetry(value => value + 1); }}><ArticleReader key={detail.id} article={detail} onRead={() => setMobileReading(true)} /></ReaderErrorBoundary> : <div className="reader-loading" role="status" style={{ aspectRatio: `${selected.cover.width} / ${selected.cover.height}` }}><span className="sr-only">Loading article</span></div>}
      </div>
    </main>
  </div>;
}
