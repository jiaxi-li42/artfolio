import { readFile } from "node:fs/promises";
import path from "node:path";
import { cache } from "react";
import type { Catalog } from "./types";

export const readCatalog = cache(async (): Promise<Catalog> => {
  try {
    return JSON.parse(await readFile(path.join(process.cwd(), "public/data/catalog.json"), "utf8"));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    return { fetchedAt: null, batchDates: [], articles: [] };
  }
});
