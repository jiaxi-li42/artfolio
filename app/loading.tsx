export default function Loading() {
  return <main className="page-status" data-route-ready="true" aria-busy="true">
    <p role="status">Loading articles…</p>
    <div className="page-placeholder" aria-hidden="true" />
  </main>;
}
