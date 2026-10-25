"use client";

import { useState } from "react";
import type { ArticleImage as ImageRecord } from "../lib/types";

export default function ArticleImage({ image, first = false, onOpen, fullSize = false, sizes }: {
  image: ImageRecord; first?: boolean; onOpen?: () => void; fullSize?: boolean; sizes?: string;
}) {
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [fallback, setFallback] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  if (failed) return <div className="reader-image-error" style={{ aspectRatio: `${image.width} / ${image.height}` }}>
    <p role="status">Image could not be loaded.</p>
    <button type="button" onClick={() => { setAttempt(attempt + 1); setFallback(null); setLoaded(false); setFailed(false); }}>Retry image</button>
  </div>;
  const sourceSet = !fallback && image.previewWidth && image.previewWidth < image.width && image.preview !== image.src
    ? `${image.preview} ${image.previewWidth}w, ${image.src} ${image.width}w` : undefined;
  const img = <img key={attempt} src={fallback ?? (fullSize ? image.src : image.preview)} srcSet={sourceSet}
    sizes={sourceSet ? sizes ?? (first
      ? "(max-width: 656px) calc(100vw - 16px), 75vw"
      : "(max-width: 656px) calc(100vw - 16px), (max-width: 768px) 45vw, 38vw") : undefined}
    className={!loaded ? "media-loading" : undefined} alt={image.alt || ""} width={image.width} height={image.height}
    loading={first ? "eager" : "lazy"} fetchPriority={first ? "high" : "auto"} decoding="async" draggable={false}
    onLoad={() => setLoaded(true)} onError={event => {
      const original = new URL(image.src, location.href).href;
      const current = event.currentTarget.currentSrc || event.currentTarget.src;
      const next = current === original ? image.preview : image.src;
      if (!fallback && new URL(next, location.href).href !== current) { setLoaded(false); setFallback(next); }
      else setFailed(true);
    }} />;
  return onOpen ? <button className="reader-image-open" type="button" aria-label={`Open image ${image.position} in gallery`} onClick={onOpen}>{img}</button> : img;
}
