"use client";

import ContentError from "../components/ContentError";

export default function ErrorPage({ retry }: { error: unknown; retry: () => void }) {
  return <main className="page-status"><ContentError onRetry={retry} /></main>;
}
