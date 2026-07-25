import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import FaceClusterView from "./FaceClusterView";

const mockInvoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

describe("FaceClusterView", () => {
  it("renders empty state when no clusters", async () => {
    mockInvoke.mockResolvedValueOnce([]);
    render(<FaceClusterView />);
    await waitFor(() =>
      expect(screen.getByText(/No clusters found/i)).toBeDefined()
    );
  });

  it("loads and displays clusters", async () => {
    mockInvoke.mockResolvedValueOnce([
      {
        cluster_id: 0,
        cluster_label: "Unknown_Person_1",
        face_count: 3,
        representative_path: "/photos/a.jpg",
        faces: [{ file_id: "f1", file_path: "/photos/a.jpg" }],
      },
    ]);
    render(<FaceClusterView />);
    await waitFor(() =>
      expect(screen.getByText(/Unknown_Person_1/i)).toBeDefined()
    );
  });

  it("starts editing when 'Name this person' is clicked", async () => {
    mockInvoke.mockResolvedValueOnce([
      {
        cluster_id: 0,
        cluster_label: "Unknown_Person_1",
        face_count: 1,
        representative_path: "/photos/a.jpg",
        faces: [{ file_id: "f1", file_path: "/photos/a.jpg" }],
      },
    ]);
    render(<FaceClusterView />);
    await waitFor(() =>
      expect(screen.getByText(/Name this person/i)).toBeDefined()
    );
    fireEvent.click(screen.getByText(/Name this person/i));
    expect(screen.getByPlaceholderText(/Type name/i)).toBeDefined();
  });

  it("calls rename_face_cluster on Enter", async () => {
    mockInvoke
      .mockResolvedValueOnce([
        {
          cluster_id: 0,
          cluster_label: "Unknown_Person_1",
          face_count: 1,
          representative_path: "/photos/a.jpg",
          faces: [{ file_id: "f1", file_path: "/photos/a.jpg" }],
        },
      ])
      .mockResolvedValueOnce({
        renamed: 1,
        tagged: 1,
        skipped: 0,
        errors: [],
        success: true,
      })
      .mockResolvedValueOnce([
        {
          cluster_id: 0,
          cluster_label: "Sarah",
          face_count: 1,
          representative_path: "/photos/a.jpg",
          faces: [{ file_id: "f1", file_path: "/photos/a.jpg" }],
        },
      ]);

    render(<FaceClusterView />);
    await waitFor(() =>
      expect(screen.getByText(/Name this person/i)).toBeDefined()
    );
    fireEvent.click(screen.getByText(/Name this person/i));
    const input = screen.getByPlaceholderText(/Type name/i);
    fireEvent.change(input, { target: { value: "Sarah" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() =>
      expect(mockInvoke).toHaveBeenCalledWith("rename_face_cluster", {
        clusterId: 0,
        newLabel: "Sarah",
      })
    );
  });

  it("cancels editing on Escape", async () => {
    mockInvoke.mockResolvedValueOnce([
      {
        cluster_id: 0,
        cluster_label: "Unknown_Person_1",
        face_count: 1,
        representative_path: "/photos/a.jpg",
        faces: [{ file_id: "f1", file_path: "/photos/a.jpg" }],
      },
    ]);
    render(<FaceClusterView />);
    await waitFor(() =>
      expect(screen.getByText(/Name this person/i)).toBeDefined()
    );
    fireEvent.click(screen.getByText(/Name this person/i));
    const input = screen.getByPlaceholderText(/Type name/i);
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByPlaceholderText(/Type name/i)).toBeNull();
  });
});
