import { describe, it, expect } from "vitest";
import {
  DEFAULT_PREFERENCES, MAX_AREAS, addAreasFromText, answer, initialAnswers,
  toPayload, toggleArea, toggleProtected, type ChoiceQuestion, type TreeChoices,
} from "./preferences";

const photosQ: ChoiceQuestion = {
  id: "photos",
  question: "How should your photos be organised?",
  options: [
    { value: "events", label: "By trip", preview: ["Photos/2023-06-10 Paris (40)"] },
    { value: "months", label: "By month", preview: ["Photos/2023-06 (40)"] },
  ],
};

describe("preference check logic", () => {
  it("starts from saved preferences, falling back to defaults", () => {
    expect(initialAnswers(null)).toEqual(DEFAULT_PREFERENCES);
    const choices = { preferences: { ...DEFAULT_PREFERENCES, photos: "months" } } as TreeChoices;
    expect(initialAnswers(choices).photos).toBe("months");
  });

  it("applies an answer only when it is one of the options", () => {
    const p = answer(DEFAULT_PREFERENCES, photosQ, "months");
    expect(p.photos).toBe("months");
    expect(answer(p, photosQ, "nonsense")).toBe(p);
  });

  it("toggles areas case-insensitively and caps them", () => {
    let areas = toggleArea([], "Work");
    expect(areas).toEqual(["Work"]);
    expect(toggleArea(areas, "work")).toEqual([]);
    areas = toggleArea(areas, "Family/Kids");
    expect(areas).toEqual(["Work", "Family Kids"]);
    let many: string[] = [];
    for (let i = 0; i < 20; i++) many = toggleArea(many, `Area ${i}`);
    expect(many).toHaveLength(MAX_AREAS);
  });

  it("adds typed areas without duplicates", () => {
    expect(addAreasFromText(["Work"], "work, Family; Admin\n ")).toEqual(["Work", "Family", "Admin"]);
  });

  it("toggles protected folders", () => {
    expect(toggleProtected([], "/a")).toEqual(["/a"]);
    expect(toggleProtected(["/a"], "/a")).toEqual([]);
  });

  it("marks the payload as answered", () => {
    expect(toPayload(DEFAULT_PREFERENCES).answered).toBe(true);
  });
});
