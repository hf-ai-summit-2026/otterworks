import { describe, it, expect } from "vitest";
import { categorize, computeInsights, resolveTopFolders } from "./insights";
import type { FileItem } from "@/types";

function file(overrides: Partial<FileItem>): FileItem {
  return {
    id: overrides.name ?? "f",
    name: "f.bin",
    mimeType: "application/octet-stream",
    size: 0,
    parentId: null,
    ownerId: "u1",
    ownerName: "",
    isFolder: false,
    path: "/",
    sharedWith: [],
    tags: [],
    createdAt: "2026-09-01T00:00:00Z",
    updatedAt: "2026-09-01T00:00:00Z",
    versions: [],
    ...overrides,
  };
}

const folders = [
  { id: "fin", name: "Finance", parentId: null },
  { id: "fin-q3", name: "Q3", parentId: "fin" },
  { id: "fin-q3-inv", name: "Invoices", parentId: "fin-q3" },
  { id: "mkt", name: "Marketing", parentId: null },
];

describe("categorize", () => {
  it("buckets by mime type and falls back to extension", () => {
    expect(categorize("image/png")).toBe("Images");
    expect(categorize("application/pdf")).toBe("PDFs");
    expect(categorize("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).toBe("Spreadsheets");
    expect(categorize("application/octet-stream", "deck.pptx")).toBe("Presentations");
    expect(categorize("text/csv", "data.csv")).toBe("Spreadsheets");
    expect(categorize("application/zip")).toBe("Archives");
    expect(categorize("application/x-unknown")).toBe("Other");
  });
});

describe("resolveTopFolders", () => {
  it("maps nested folders to their top-level ancestor", () => {
    const top = resolveTopFolders(folders);
    expect(top.get("fin-q3-inv")).toBe("Finance");
    expect(top.get("fin")).toBe("Finance");
    expect(top.get("mkt")).toBe("Marketing");
  });

  it("survives cycles", () => {
    const top = resolveTopFolders([
      { id: "a", name: "A", parentId: "b" },
      { id: "b", name: "B", parentId: "a" },
    ]);
    expect(top.size).toBe(2);
  });
});

describe("computeInsights", () => {
  const now = new Date("2026-10-21T00:00:00Z");
  const files = [
    file({ id: "1", name: "logo.png", mimeType: "image/png", size: 500, parentId: "mkt" }),
    file({ id: "2", name: "inv.pdf", mimeType: "application/pdf", size: 2000, parentId: "fin-q3-inv" }),
    file({ id: "3", name: "inv.pdf", mimeType: "application/pdf", size: 2000, parentId: "fin-q3" }),
    file({
      id: "4",
      name: "old.zip",
      mimeType: "application/zip",
      size: 100,
      createdAt: "2025-01-15T00:00:00Z",
      updatedAt: "2025-01-15T00:00:00Z",
    }),
    file({ id: "5", name: "gone.png", mimeType: "image/png", size: 9999, isTrashed: true }),
  ];
  const insights = computeInsights(files, folders, now);

  it("totals live files only", () => {
    expect(insights.totalFiles).toBe(4);
    expect(insights.totalBytes).toBe(4600);
    expect(insights.averageBytes).toBe(1150);
  });

  it("groups by category, sorted by bytes", () => {
    expect(insights.byCategory.map((c) => c.category)).toEqual(["PDFs", "Images", "Archives"]);
  });

  it("rolls files up to their top-level folder", () => {
    expect(insights.byTopFolder).toEqual([
      { label: "Finance", count: 2, bytes: 4000 },
      { label: "Marketing", count: 1, bytes: 500 },
      { label: "Unfiled", count: 1, bytes: 100 },
    ]);
  });

  it("buckets uploads by month in order", () => {
    expect(insights.byMonth.map((m) => m.label)).toEqual(["2025-01", "2026-09"]);
  });

  it("buckets files by size", () => {
    expect(insights.bySize.map((b) => b.count)).toEqual([4, 0, 0, 0, 0, 0]);
    expect(insights.bySize[0].label).toBe("< 10 KB");
  });

  it("flags stale files", () => {
    expect(insights.staleFiles).toBe(1);
    expect(insights.staleBytes).toBe(100);
  });

  it("finds duplicates by name and size", () => {
    expect(insights.duplicates).toHaveLength(1);
    expect(insights.duplicates[0].files.map((f) => f.id)).toEqual(["2", "3"]);
    expect(insights.reclaimableBytes).toBe(2000);
  });

  it("lists the largest files first", () => {
    expect(insights.largest[0].size).toBe(2000);
    expect(insights.largest).toHaveLength(4);
  });
});
