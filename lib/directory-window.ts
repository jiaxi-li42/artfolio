export function directoryWindow(index: number, total: number, viewportRows = 10) {
  const size = Math.max(36, viewportRows + 24);
  const start = Math.max(0, Math.min(Math.floor((index - 12) / 6) * 6, total - size));
  return { start, end: Math.min(total, start + size) };
}

export function directoryLayout(width: number, height: number) {
  const step = width <= 768 ? 86 : 106;
  const rows = Math.max(1, Math.floor((height - 200) / step));
  return { step, header: Math.max(260, height - rows * step + (width <= 768 ? 40 : 53)), viewportRows: Math.ceil(height / step) };
}

export function restoredDirectoryScroll(entry: { scroll?: number; step?: number; header?: number }, width: number, height: number) {
  if (!Number.isFinite(entry.scroll) || entry.scroll! < 0) return 0;
  const layout = directoryLayout(width, height);
  const previousStep = entry.step === 86 || entry.step === 106 ? entry.step : layout.step;
  const previousHeader = Number.isFinite(entry.header) && entry.header! >= 260 ? entry.header! : layout.header;
  return entry.scroll! > previousHeader ? layout.header + (entry.scroll! - previousHeader) / previousStep * layout.step : entry.scroll!;
}
