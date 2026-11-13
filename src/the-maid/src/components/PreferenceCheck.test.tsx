// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import PreferenceCheck from "./PreferenceCheck";

// Calls are recorded by a vi.fn spy; responses come from a plain function so a
// rejected promise is not also tracked (and reported as unhandled) by the spy.
const mockInvoke = vi.fn();
let respond: (cmd: string) => Promise<unknown> = () => Promise.resolve({});
vi.mock("@tauri-apps/api/core", () => ({
  invoke: (cmd: string, args?: unknown) => { mockInvoke(cmd, args); return respond(cmd); },
}));

const choices = {
  questions: [{
    id: "photos",
    question: "How should your 40 photos be organised?",
    options: [
      { value: "events", label: "By trip or event", preview: ["Photos/2023-06-10 Paris (40)"] },
      { value: "months", label: "By year and month", preview: ["Photos/2023-06 (40)"] },
    ],
  }],
  suggested_areas: ["Work", "Family"],
  protect_candidates: [{ path: "/home/v/Projects/Boat", name: "Projects/Boat", files: 12 }],
  preferences: { inside_topics: "auto", photos: "events", depth: "detailed", areas: [], protected: [], answered: false },
};

describe("PreferenceCheck", () => {
  beforeEach(() => mockInvoke.mockReset());

  it("shows choices previewed on the user's files and saves the answers", async () => {
    respond = (cmd) => Promise.resolve(cmd === "get_tree_choices" ? choices : {});
    const onDone = vi.fn();
    render(<PreferenceCheck files={[]} directory="/home/v" onDone={onDone} onCancel={() => {}} />);

    await waitFor(() => expect(screen.getByText(/How should your 40 photos/)).toBeDefined());
    expect(screen.getByText("Photos/2023-06 (40)")).toBeDefined();

    fireEvent.click(screen.getByText("By year and month"));
    fireEvent.click(screen.getByText("Work"));
    fireEvent.click(screen.getByLabelText(/Projects\/Boat/));
    fireEvent.change(screen.getByPlaceholderText(/Add your own/), { target: { value: "Boat club" } });
    fireEvent.click(screen.getByText("Build my tree"));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    const saveCall = mockInvoke.mock.calls.find((c) => c[0] === "save_preferences");
    expect(saveCall![1].preferences).toMatchObject({
      photos: "months",
      areas: ["Work", "Boat club"],
      protected: ["/home/v/Projects/Boat"],
      answered: true,
    });
  });

  it("shows the error and stays open when loading fails", async () => {
    respond = () => Promise.reject(new Error("backend down"));
    render(<PreferenceCheck files={[]} directory="/x" onDone={() => {}} onCancel={() => {}} />);
    await waitFor(() => expect(screen.getByText(/backend down/)).toBeDefined());
    expect(screen.getByText("Build my tree")).toBeDefined();
  });
});
