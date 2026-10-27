"use client";

import { useState } from "react";
import type { ArticleImage as ImageRecord } from "../lib/types";

type ImageProps = {
  image: ImageRecord; first?: boolean; onOpen?: () => void; fullSize?: boolean; sizes?: string;
};

function ImageError({ image, onRetry }: { image: ImageRecord; onRetry: () => void }) {
  return <div className="reader-image-error" style={{ aspectRatio: `${image.width} / ${image.height}` }}>
    <p role="status">Image could not be loaded.</p>
    <button type="button" onClick={onRetry}>Retry image</button>
  </div>;
}

function GalleryMedia({ image, active }: { image: ImageRecord; active: boolean }) {
  const [ready, setReady] = useState(false);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [originalFailed, setOriginalFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  if (previewFailed && originalFailed) return <ImageError image={image} onRetry={() => {
    setReady(false); setPreviewFailed(false); setOriginalFailed(false); setAttempt(value => value + 1);
  }} />;
  return <span key={attempt} className="gallery-media" data-ready={ready} role="img" aria-label={image.alt || `Image ${image.position}`}
    style={{ aspectRatio: `${image.width} / ${image.height}` }}>
    <img src={image.preview} alt="" aria-hidden="true" hidden={previewFailed} width={image.width} height={image.height}
      loading="eager" fetchPriority={active ? "high" : "low"} decoding="async" draggable={false} onError={() => setPreviewFailed(true)} />
    <img className="gallery-original" src={image.src} alt="" aria-hidden="true" hidden={originalFailed} width={image.width} height={image.height}
      loading="eager" fetchPriority={active ? "auto" : "low"} decoding="async" draggable={false} onError={() => setOriginalFailed(true)}
      onLoad={async event => {
        const element = event.currentTarget;
        try {
          await element.decode();
          if (element.isConnected) setReady(true);
        } catch { if (element.isConnected) setOriginalFailed(true); }
      }} />
  </span>;
}

export default function ArticleImage(props: ImageProps) {
  return props.fullSize && props.image.preview !== props.image.src
    ? <GalleryMedia key={props.image.id} image={props.image} active={props.first ?? false} />
    : <StandardImage {...props} />;
}

function StandardImage({ image, first = false, onOpen, fullSize = false, sizes }: ImageProps) {
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [fallback, setFallback] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  if (failed) return <ImageError image={image} onRetry={() => { setAttempt(attempt + 1); setFallback(null); setLoaded(false); setFailed(false); }} />;
  const sourceSet = !fallback && image.previewWidth && image.previewWidth < image.width && image.preview !== image.src
    ? `${image.preview} ${image.previewWidth}w, ${image.src} ${image.width}w` : undefined;
  const img = <img key={attempt} src={fallback ?? (fullSize ? image.src : image.preview)} srcSet={sourceSet}
    sizes={sourceSet ? sizes ?? (first
      ? "(max-width: 656px) calc(100vw - 16px), 75vw"
      : "(max-width: 656px) calc(100vw - 16px), (max-width: 768px) 45vw, 38vw") : undefined}
    className={!loaded ? "media-loading" : undefined} alt={image.alt || ""} width={image.width} height={image.height}
    loading={fullSize || first ? "eager" : "lazy"} fetchPriority={first ? "high" : fullSize ? "low" : "auto"} decoding="async" draggable={false}
    onLoad={() => setLoaded(true)} onError={event => {
      const original = new URL(image.src, location.href).href;
      const current = event.currentTarget.currentSrc || event.currentTarget.src;
      const next = current === original ? image.preview : image.src;
      if (!fallback && new URL(next, location.href).href !== current) { setLoaded(false); setFallback(next); }
      else setFailed(true);
    }} />;
  return onOpen ? <button className="reader-image-open" type="button" aria-label={`Open image ${image.position} in gallery`} onClick={onOpen}>{img}</button> : img;
}
