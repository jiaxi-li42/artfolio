"use client";

import { useState } from "react";
import type { ArticleImage as ImageRecord } from "../lib/types";

export default function ArticleImage({ image, first = false, onOpen }: { image: ImageRecord; first?: boolean; onOpen?: () => void }) {
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  if (failed) return <div className="reader-image-error" style={{ aspectRatio: `${image.width} / ${image.height}` }}>
    <p role="status">Image could not be loaded.</p>
    <button type="button" onClick={() => { setAttempt(attempt + 1); setFailed(false); }}>Retry image</button>
  </div>;
  const img = <img key={attempt} src={image.preview} alt={image.alt || ""} width={image.width} height={image.height}
    loading={first ? "eager" : "lazy"} fetchPriority={first ? "high" : "auto"} decoding="async" draggable={false} onError={() => setFailed(true)} />;
  return onOpen ? <button className="reader-image-open" type="button" aria-label={`Open image ${image.position} in gallery`} onClick={onOpen}>{img}</button> : img;
}
