export function londonDate(stamp: string) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/London", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date(stamp));
}

export function updatedLabel(stamp: string) {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "Europe/London", weekday: "long", month: "long", day: "numeric",
  }).format(new Date(stamp));
}

export function parseBatchDate(value: string) {
  if (!/^\d{6}$/.test(value)) return null;
  const day = Number(value.slice(0, 2));
  const month = Number(value.slice(2, 4));
  const year = 2000 + Number(value.slice(4, 6));
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return date.toISOString().slice(0, 10);
}
