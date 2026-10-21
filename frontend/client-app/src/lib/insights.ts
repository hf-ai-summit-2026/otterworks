import type { FileItem } from "@/types";

export type FileCategory =
  | "Images"
  | "Video"
  | "Audio"
  | "PDFs"
  | "Spreadsheets"
  | "Presentations"
  | "Documents"
  | "Text & data"
  | "Archives"
  | "Other";

export interface FolderNode {
  id: string;
  name: string;
  parentId: string | null;
}

export interface CategoryStat {
  category: FileCategory;
  count: number;
  bytes: number;
}

export interface BucketStat {
  label: string;
  count: number;
  bytes: number;
}

export interface DuplicateGroup {
  name: string;
  size: number;
  files: FileItem[];
  wastedBytes: number;
}

export interface StorageInsights {
  totalFiles: number;
  totalBytes: number;
  averageBytes: number;
  staleFiles: number;
  staleBytes: number;
  byCategory: CategoryStat[];
  byTopFolder: BucketStat[];
  byMonth: BucketStat[];
  bySize: BucketStat[];
  largest: FileItem[];
  duplicates: DuplicateGroup[];
  reclaimableBytes: number;
}

export const STALE_AFTER_DAYS = 180;

const SIZE_BUCKETS: Array<{ label: string; max: number }> = [
  { label: "< 10 KB", max: 10 * 1024 },
  { label: "10–50 KB", max: 50 * 1024 },
  { label: "50–100 KB", max: 100 * 1024 },
  { label: "100 KB–1 MB", max: 1024 * 1024 },
  { label: "1–10 MB", max: 10 * 1024 * 1024 },
  { label: "> 10 MB", max: Infinity },
];
const UNFILED = "Unfiled";

export function categorize(mimeType: string, name = ""): FileCategory {
  const mime = mimeType.toLowerCase();
  const ext = name.toLowerCase().split(".").pop() ?? "";
  if (mime.startsWith("image/")) return "Images";
  if (mime.startsWith("video/")) return "Video";
  if (mime.startsWith("audio/")) return "Audio";
  if (mime === "application/pdf" || ext === "pdf") return "PDFs";
  if (mime.includes("spreadsheet") || mime.includes("excel") || ["xlsx", "xls", "csv"].includes(ext))
    return "Spreadsheets";
  if (mime.includes("presentation") || mime.includes("powerpoint") || ["pptx", "ppt"].includes(ext))
    return "Presentations";
  if (mime.includes("wordprocessing") || mime.includes("msword") || ["docx", "doc", "rtf"].includes(ext))
    return "Documents";
  if (mime.startsWith("text/") || mime.includes("json") || mime.includes("xml") || mime.includes("yaml"))
    return "Text & data";
  if (mime.includes("zip") || mime.includes("tar") || mime.includes("gzip") || mime.includes("compressed"))
    return "Archives";
  return "Other";
}

/** Map every folder id to the name of its top-level ancestor. */
export function resolveTopFolders(folders: FolderNode[]): Map<string, string> {
  const byId = new Map(folders.map((f) => [f.id, f]));
  const result = new Map<string, string>();
  for (const folder of folders) {
    const seen = new Set<string>();
    let current: FolderNode | undefined = folder;
    while (current?.parentId && byId.has(current.parentId) && !seen.has(current.id)) {
      seen.add(current.id);
      current = byId.get(current.parentId);
    }
    result.set(folder.id, current?.name ?? folder.name);
  }
  return result;
}

function bump(map: Map<string, BucketStat>, label: string, bytes: number) {
  const entry = map.get(label) ?? { label, count: 0, bytes: 0 };
  entry.count += 1;
  entry.bytes += bytes;
  map.set(label, entry);
}

export function computeInsights(
  files: FileItem[],
  folders: FolderNode[] = [],
  now: Date = new Date(),
): StorageInsights {
  const live = files.filter((f) => !f.isTrashed && !f.isFolder);
  const topFolder = resolveTopFolders(folders);
  const staleCutoff = now.getTime() - STALE_AFTER_DAYS * 24 * 60 * 60 * 1000;

  const categories = new Map<FileCategory, CategoryStat>();
  const tops = new Map<string, BucketStat>();
  const months = new Map<string, BucketStat>();
  const dupes = new Map<string, FileItem[]>();
  const sizes = SIZE_BUCKETS.map(({ label }) => ({ label, count: 0, bytes: 0 }));
  let totalBytes = 0;
  let staleFiles = 0;
  let staleBytes = 0;

  for (const file of live) {
    const size = file.size || 0;
    totalBytes += size;

    const category = categorize(file.mimeType, file.name);
    const cat = categories.get(category) ?? { category, count: 0, bytes: 0 };
    cat.count += 1;
    cat.bytes += size;
    categories.set(category, cat);

    bump(tops, (file.parentId && topFolder.get(file.parentId)) || UNFILED, size);

    const sizeBucket = sizes[SIZE_BUCKETS.findIndex((b) => size < b.max)];
    sizeBucket.count += 1;
    sizeBucket.bytes += size;

    const created = new Date(file.createdAt);
    if (!Number.isNaN(created.getTime())) {
      bump(months, created.toISOString().slice(0, 7), size);
    }

    const touched = new Date(file.updatedAt || file.createdAt).getTime();
    if (!Number.isNaN(touched) && touched < staleCutoff) {
      staleFiles += 1;
      staleBytes += size;
    }

    const key = `${file.name.toLowerCase()}::${size}`;
    const group = dupes.get(key);
    if (group) group.push(file);
    else dupes.set(key, [file]);
  }

  const duplicates: DuplicateGroup[] = [...dupes.values()]
    .filter((g) => g.length > 1)
    .map((g) => ({
      name: g[0].name,
      size: g[0].size,
      files: g,
      wastedBytes: g[0].size * (g.length - 1),
    }))
    .sort((a, b) => b.wastedBytes - a.wastedBytes || b.files.length - a.files.length);

  return {
    totalFiles: live.length,
    totalBytes,
    averageBytes: live.length ? Math.round(totalBytes / live.length) : 0,
    staleFiles,
    staleBytes,
    byCategory: [...categories.values()].sort((a, b) => b.bytes - a.bytes),
    byTopFolder: [...tops.values()].sort((a, b) => b.bytes - a.bytes),
    byMonth: [...months.values()].sort((a, b) => a.label.localeCompare(b.label)),
    bySize: sizes,
    largest: [...live].sort((a, b) => b.size - a.size).slice(0, 10),
    duplicates,
    reclaimableBytes: duplicates.reduce((sum, d) => sum + d.wastedBytes, 0),
  };
}
