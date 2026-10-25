"use client";

import { createContext, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

export const ArchiveNavigation = createContext<(href: string) => void>(() => {});

export default function ArchiveTransition({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const root = useRef<HTMLDivElement>(null);
  const destination = useRef<string | null>(null);
  const focusAfterEnter = useRef(false);
  const [phase, setPhase] = useState<"idle" | "leaving" | "waiting" | "entering">("idle");

  const reset = useCallback(() => { destination.current = null; setPhase("idle"); }, []);
  const navigate = useCallback((href: string) => {
    if (destination.current) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) { router.push(href); return; }
    destination.current = href;
    setPhase("leaving");
  }, [router]);

  useEffect(() => {
    window.addEventListener("popstate", reset);
    return () => window.removeEventListener("popstate", reset);
  }, [reset]);

  useLayoutEffect(() => {
    const element = root.current;
    if (!element) return;
    if (phase === "idle") {
      element.style.removeProperty("opacity");
      if (focusAfterEnter.current) {
        focusAfterEnter.current = false;
        const selector = location.pathname === "/all" ? "#all-articles-heading" : innerWidth <= 656 && location.pathname === "/" ? ".show-all" : "#reader-heading, .empty-state button";
        [...element.querySelectorAll<HTMLElement>(selector)].find(target => target.getClientRects().length)?.focus({ preventScroll: true });
      }
      return;
    }
    if (phase === "waiting") return;
    const leaving = phase === "leaving";
    const reduced = matchMedia("(prefers-reduced-motion: reduce)");
    const complete = () => {
      if (leaving && destination.current) {
        element.style.opacity = "0";
        setPhase("waiting");
        router.push(destination.current);
      } else {
        if (!leaving) focusAfterEnter.current = true;
        reset();
      }
    };
    const animation = element.animate([{ opacity: leaving ? 1 : 0 }, { opacity: leaving ? 0 : 1 }], {
      duration: reduced.matches ? 0 : 300, easing: "ease", fill: "forwards",
    });
    animation.onfinish = complete;
    const reduce = () => { if (reduced.matches) animation.finish(); };
    reduced.addEventListener("change", reduce);
    return () => { animation.onfinish = null; animation.cancel(); reduced.removeEventListener("change", reduce); };
  }, [phase, router, reset]);

  useLayoutEffect(() => {
    if (phase !== "waiting" || !root.current || !destination.current) return;
    const element = root.current;
    let frame = 0;
    const reveal = () => {
      if (!destination.current || pathname !== new URL(destination.current, location.origin).pathname) return;
      const page = [...element.querySelectorAll<HTMLElement>('[data-route-ready="true"]')].find(page => page.getClientRects().length);
      if (!page || page.dataset.routeReady !== "true") return;
      observer.disconnect();
      // Allow the directory's scheduled ScrollTrigger refresh and positioning to finish first.
      frame = requestAnimationFrame(() => setPhase("entering"));
    };
    const observer = new MutationObserver(reveal);
    observer.observe(element, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-route-ready"] });
    reveal();
    // A failed navigation must not leave the previous page invisible or inert.
    const timeout = setTimeout(reset, 10000);
    return () => { observer.disconnect(); cancelAnimationFrame(frame); clearTimeout(timeout); };
  }, [phase, pathname, reset]);

  return <ArchiveNavigation value={navigate}>
    <div ref={root} data-archive-phase={phase} aria-busy={phase !== "idle"} inert={phase !== "idle"}>{children}</div>
    {phase === "waiting" && <span className="sr-only" role="status">Loading articles…</span>}
  </ArchiveNavigation>;
}
