"use client";

export default function ContentError({ onRetry }: { onRetry: () => void }) {
  return <div className="empty-state" role="alert" data-route-ready="true">
    <p>This content couldn’t be loaded.</p>
    <p>Please try again in a moment.</p>
    <button type="button" onClick={onRetry}>Try again</button>
  </div>;
}
