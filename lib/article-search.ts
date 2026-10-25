export const articleSources = [
  { id: "teeth", label: "Teeth Magazine" },
  { id: "aperture", label: "Aperture" },
  { id: "itsnicethat", label: "It’s Nice That" },
  { id: "c41", label: "C41 Magazine" },
  { id: "phroom", label: "PHROOM" },
];

export const sourceOption = (id: string) => articleSources.find(source => source.id === id);
const normalise = (value: string) => value.normalize("NFKC").toLowerCase().replace(/[‘’]/g, "'").replace(/[“”]/g, '"').replace(/\s+/g, " ").trim();

export function articleMatches(article: { source: string; sourceLabel: string; title: string }, query: string, source: string) {
  if (source) return article.source === source;
  const text = normalise(`${article.sourceLabel} ${article.title}`);
  return normalise(query).split(" ").filter(Boolean).every(term => text.includes(term));
}
