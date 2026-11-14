// The Maid — tree preference check: pure logic (kept out of the component for tests)

export type InsideTopics = "auto" | "year" | "type";
export type PhotosStyle = "events" | "months";
export type Depth = "detailed" | "shallow";

export interface TreePreferences {
  inside_topics: InsideTopics;
  photos: PhotosStyle;
  depth: Depth;
  areas: string[];
  protected: string[];
  answered: boolean;
}

export interface ChoiceOption {
  value: string;
  label: string;
  preview: string[];
}

export interface ChoiceQuestion {
  id: "inside_topics" | "photos" | "depth";
  question: string;
  options: ChoiceOption[];
}

export interface ProtectCandidate {
  path: string;
  name: string;
  files: number;
}

export interface TreeChoices {
  questions: ChoiceQuestion[];
  suggested_areas: string[];
  protect_candidates: ProtectCandidate[];
  preferences: TreePreferences;
}

export const DEFAULT_PREFERENCES: TreePreferences = {
  inside_topics: "auto",
  photos: "events",
  depth: "detailed",
  areas: [],
  protected: [],
  answered: false,
};

export const MAX_AREAS = 8;

/** Start from what the user saved before (or the defaults). */
export function initialAnswers(choices: TreeChoices | null): TreePreferences {
  return { ...DEFAULT_PREFERENCES, ...(choices?.preferences ?? {}) };
}

/** Apply the option picked for one question. Unknown values are ignored. */
export function answer(prefs: TreePreferences, q: ChoiceQuestion, value: string): TreePreferences {
  if (!q.options.some((o) => o.value === value)) return prefs;
  return { ...prefs, [q.id]: value } as TreePreferences;
}

function cleanArea(text: string): string {
  return text.replace(/[\\/]/g, " ").replace(/\s+/g, " ").trim().slice(0, 40);
}

/** Toggle an area on/off (case-insensitive), capped at MAX_AREAS. */
export function toggleArea(areas: string[], area: string): string[] {
  const a = cleanArea(area);
  if (!a) return areas;
  const exists = areas.some((x) => x.toLowerCase() === a.toLowerCase());
  if (exists) return areas.filter((x) => x.toLowerCase() !== a.toLowerCase());
  return areas.length >= MAX_AREAS ? areas : [...areas, a];
}

/** "Work, Family; Admin" → adds each area not already there. */
export function addAreasFromText(areas: string[], text: string): string[] {
  let out = areas;
  for (const part of text.split(/[,;\n]/)) {
    const a = cleanArea(part);
    if (a && !out.some((x) => x.toLowerCase() === a.toLowerCase())) out = toggleArea(out, a);
  }
  return out;
}

export function toggleProtected(paths: string[], path: string): string[] {
  return paths.includes(path) ? paths.filter((p) => p !== path) : [...paths, path];
}

/** Payload sent to the backend when the user confirms. */
export function toPayload(prefs: TreePreferences): TreePreferences {
  return { ...prefs, areas: prefs.areas.map(cleanArea).filter(Boolean), answered: true };
}
