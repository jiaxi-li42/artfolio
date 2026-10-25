"use client";

import { useLayoutEffect, useRef, useState } from "react";
import MaterialIcon from "./MaterialIcon";
import { gsap } from "gsap";
import { CustomEase } from "gsap/CustomEase";
import { Swiper, SwiperSlide } from "swiper/react";
import { EffectFade, Keyboard, Navigation, Pagination, Virtual } from "swiper/modules";
import type { Swiper as SwiperInstance } from "swiper";
import type { ArticleDetail, ArticleImage as ImageRecord } from "../lib/types";
import ArticleImage from "./ArticleImage";
import "swiper/css";
import "swiper/css/effect-fade";
import "swiper/css/pagination";
import "./gallery.css";

gsap.registerPlugin(CustomEase);
const galleryEase = CustomEase.create("gallery-css-ease", "M0,0 C0.25,0.1 0.25,1 1,1");

function GalleryImage({ image, index, active, viewport }: { image: ImageRecord; index: number; active: boolean; viewport: { width: number; height: number } }) {
  const caption = useRef<HTMLElement>(null);
  const [captionHeight, setCaptionHeight] = useState(0);
  useLayoutEffect(() => {
    const element = caption.current;
    if (!element) return;
    const measure = () => setCaptionHeight(Math.ceil(element.getBoundingClientRect().height));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const width = Math.max(1, Math.min(viewport.width - 16, (viewport.height - 112 - captionHeight - (image.caption.trim() ? 8 : 0)) * image.width / image.height));
  return <figure className="gallery-figure" data-index={index} data-image-id={image.id} style={{ width }}>
    <ArticleImage image={image} first={active} />
    {image.caption.trim() && <figcaption ref={caption} tabIndex={active ? 0 : -1} className="reader-caption gallery-caption swiper-no-swiping">{image.caption}</figcaption>}
  </figure>;
}

export default function ImageGallery({ article, initialIndex, onLocate, onClose }: { article: ArticleDetail; initialIndex: number; onLocate: (index: number) => void; onClose: (index: number) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const inner = useRef<HTMLDivElement>(null);
  const cursor = useRef<HTMLDivElement>(null);
  const swiper = useRef<SwiperInstance | null>(null);
  const timeline = useRef<gsap.core.Timeline | null>(null);
  const closing = useRef(false);
  const currentIndex = useRef(initialIndex);
  const previousGutter = useRef("");
  const [index, setIndex] = useState(initialIndex);
  const [phase, setPhase] = useState("entering");
  const [touch, setTouch] = useState(() => "ontouchstart" in window || navigator.maxTouchPoints > 0);
  const [viewport, setViewport] = useState(() => ({ width: window.innerWidth, height: window.innerHeight }));

  useLayoutEffect(() => {
    const element = dialog.current!, content = inner.current!;
    const previousOverflow = document.documentElement.style.overflow;
    previousGutter.current = document.documentElement.style.scrollbarGutter;
    document.documentElement.style.overflow = "hidden";
    document.documentElement.style.scrollbarGutter = "auto";
    element.showModal();
    element.querySelector<HTMLButtonElement>(".gallery-close")?.focus();
    const resize = () => {
      setViewport({ width: window.innerWidth, height: window.innerHeight });
      setTouch("ontouchstart" in window || navigator.maxTouchPoints > 0);
    };
    const pointer = matchMedia("(pointer: coarse)");
    window.addEventListener("resize", resize);
    pointer.addEventListener("change", resize);
    const duration = matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : .5;
    timeline.current = gsap.timeline().to(element, { opacity: 1, duration, ease: galleryEase })
      .to(content, { opacity: 1, duration, ease: galleryEase }).call(() => setPhase("open"));
    return () => {
      timeline.current?.kill();
      gsap.killTweensOf([element, content]);
      window.removeEventListener("resize", resize);
      pointer.removeEventListener("change", resize);
      element.close();
      document.documentElement.style.overflow = previousOverflow;
      document.documentElement.style.scrollbarGutter = previousGutter.current;
    };
  }, []);

  function close() {
    if (closing.current) return;
    closing.current = true;
    setPhase("closing");
    timeline.current?.kill();
    swiper.current?.keyboard.disable();
    const duration = matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : .5;
    timeline.current = gsap.timeline().set(dialog.current, { pointerEvents: "none" })
      .to(inner.current, { opacity: 0, duration, ease: galleryEase })
      .call(() => {
        document.documentElement.style.scrollbarGutter = previousGutter.current;
        onLocate(currentIndex.current);
      })
      .to(dialog.current, { opacity: 0, duration, ease: galleryEase })
      .call(() => onClose(currentIndex.current));
  }

  return <dialog ref={dialog} className="image-gallery" data-touch={touch} data-phase={phase} aria-labelledby="gallery-title" onCancel={event => { event.preventDefault(); close(); }} onKeyDown={event => {
    if (event.key !== "Tab") return;
    const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), [tabindex="0"]')].filter(element => !element.closest("[inert]") && element.getClientRects().length && getComputedStyle(element).visibility !== "hidden");
    const first = controls[0], last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first || !event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      (event.shiftKey ? last : first)?.focus();
    }
  }}>
    <h2 id="gallery-title" className="sr-only">{article.title} — image gallery</h2>
    <div className="gallery-inner" ref={inner}>
      <div className="gallery-top"><button className="gallery-close" type="button" aria-label="Close image gallery" onClick={close} onTouchEnd={event => { event.preventDefault(); close(); }}><MaterialIcon name="close" /></button></div>
      <Swiper key={touch ? "touch" : "mouse"} className="gallery-stage" modules={[EffectFade, Keyboard, Navigation, Pagination, Virtual]} initialSlide={index} slidesPerView={1} speed={matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 300}
        effect={touch ? "slide" : "fade"} fadeEffect={{ crossFade: true }} virtual={touch} loop={false}
        threshold={5} touchRatio={1} touchAngle={45} followFinger longSwipes longSwipesMs={300} longSwipesRatio={.5} shortSwipes resistance resistanceRatio={.85} simulateTouch={touch}
        keyboard={{ enabled: !touch, onlyInViewport: true, pageUpDown: true }}
        navigation={touch ? false : { prevEl: ".gallery-previous", nextEl: ".gallery-next", addIcons: false }}
        pagination={{ el: ".gallery-bullets", dynamicBullets: true, dynamicMainBullets: 3, clickable: false }}
        onSwiper={instance => { swiper.current = instance; }} onSlideChange={instance => {
          currentIndex.current = instance.realIndex;
          setIndex(instance.realIndex);
          if (instance.isBeginning || instance.isEnd) cursor.current?.classList.remove("visible");
        }}>
        {article.images.map((image, itemIndex) => <SwiperSlide key={image.id} virtualIndex={itemIndex} data-image-id={image.id} inert={itemIndex !== index} aria-hidden={itemIndex !== index}>
          {Math.abs(itemIndex - index) <= 1 && <GalleryImage image={image} index={itemIndex} active={itemIndex === index} viewport={viewport} />}
        </SwiperSlide>)}
        {!touch && <div className="gallery-nav" slot="container-end" onMouseMove={event => {
          if (!cursor.current) return;
          cursor.current.style.transform = `translate3d(${event.clientX}px, ${event.clientY}px, 0)`;
        }} onMouseLeave={() => cursor.current?.classList.remove("visible")}>
          <button className="gallery-step gallery-previous" type="button" aria-label="Previous image" onMouseEnter={() => { cursor.current?.classList.remove("next"); cursor.current?.classList.add("visible", "previous"); }} />
          <button className="gallery-step gallery-next" type="button" aria-label="Next image" onMouseEnter={() => { cursor.current?.classList.remove("previous"); cursor.current?.classList.add("visible", "next"); }} />
        </div>}
      </Swiper>
      <div className="gallery-pagination"><div className="gallery-bullets swiper-pagination" /></div>
      <p className="sr-only" role="status" aria-live="polite">Image {index + 1} of {article.images.length}</p>
      {!touch && <div className="gallery-cursor" ref={cursor} aria-hidden="true"><MaterialIcon name="chevron_left" /><MaterialIcon name="chevron_right" /></div>}
    </div>
  </dialog>;
}
