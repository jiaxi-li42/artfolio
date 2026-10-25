import { readFile } from "node:fs/promises";
import path from "node:path";
import { cache } from "react";
import type { Catalog } from "./types";
import { contentBaseUrl, isContentVersion, readRemoteContent } from "./remote-content";
import { validateCatalog } from "./content-validation";

let lastGood: { version: string; catalog: Catalog } | undefined;

export const readCatalog = cache(async (): Promise<Catalog> => {
  if (contentBaseUrl()) {
    try {
      const pointer = await readRemoteContent("current.json") as { version?: string };
      if (!pointer.version || !isContentVersion(pointer.version)) throw new Error("Invalid release pointer");
      if (lastGood?.version === pointer.version) return lastGood.catalog;
      const catalog = validateCatalog(await readRemoteContent(`releases/${pointer.version}/catalog.json`, pointer.version));
      lastGood = { version: pointer.version, catalog };
      return catalog;
    } catch (error) {
      if (!lastGood) throw error;
      console.error("External catalog unavailable; serving the last validated release", error);
      return lastGood.catalog;
    }
  }
  try {
    return validateCatalog(JSON.parse(await readFile(path.join(process.cwd(), "public/data/catalog.json"), "utf8")));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    return { fetchedAt: null, batchDates: [], articles: [] };
  }
});
