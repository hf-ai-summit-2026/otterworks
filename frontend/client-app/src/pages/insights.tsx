import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import toast from "react-hot-toast";
import { Archive, Copy, FileText, HardDrive, Hourglass, PieChart as PieIcon, Trash2 } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AppShell } from "@/components/layout/app-shell";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { EmptyState } from "@/components/ui/empty-state";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DashboardSkeleton } from "@/components/ui/skeleton";
import { filesApi } from "@/lib/api";
import {
  computeInsights,
  duplicateExtras,
  largestFiles,
  STALE_AFTER_DAYS,
} from "@/lib/insights";
import type { DuplicateGroup, FileCategory, FolderNode, InsightFilter } from "@/lib/insights";
import { formatFileSize, formatRelativeTime, runDeletions } from "@/lib/utils";

interface DeleteRequest {
  ids: string[];
  title: string;
  description: string;
}

const CATEGORY_COLORS = [
  "#2563eb", "#7c3aed", "#16a34a", "#ea580c", "#0891b2",
  "#db2777", "#ca8a04", "#4b5563", "#dc2626", "#9ca3af",
];

export default function InsightsPage() {
  return (
    <AppShell>
      <ErrorBoundary>
        <InsightsContent />
      </ErrorBoundary>
    </AppShell>
  );
}

function InsightsContent() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<InsightFilter>({});
  const [deleteRequest, setDeleteRequest] = useState<DeleteRequest | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const files = useQuery({
    queryKey: ["files", "all"],
    queryFn: () => filesApi.listAll(),
    staleTime: 5 * 60 * 1000,
  });
  const folders = useQuery({
    queryKey: ["folders", "tree"],
    queryFn: () => filesApi.listFolderTree(),
    staleTime: 5 * 60 * 1000,
  });

  const folderNodes = useMemo<FolderNode[]>(
    () => (folders.data ?? []).map((f) => ({ id: f.id, name: f.name, parentId: f.parentId })),
    [folders.data],
  );
  const insights = useMemo(
    () =>
      files.data
        ? computeInsights(files.data, folderNodes)
        : null,
    [files.data, folderNodes],
  );
  const largest = useMemo(
    () => largestFiles(files.data ?? [], folderNodes, filter),
    [files.data, folderNodes, filter],
  );

  const toggleCategoryFilter = (category: FileCategory) => {
    setFilter((active) => active.category === category ? {} : { category });
  };
  const toggleFolderFilter = (topFolder: string) => {
    setFilter((active) => active.topFolder === topFolder ? {} : { topFolder });
  };

  const confirmDeletion = async () => {
    if (!deleteRequest || isDeleting) return;
    setIsDeleting(true);
    const result = await runDeletions(deleteRequest.ids, filesApi.delete);

    queryClient.invalidateQueries({ queryKey: ["files"] });
    queryClient.invalidateQueries({ queryKey: ["folders"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    queryClient.invalidateQueries({ queryKey: ["storage", "usage"] });

    if (result.succeeded > 0) {
      toast.success(`${result.succeeded} file${result.succeeded === 1 ? "" : "s"} moved to trash`);
    }
    if (result.failed > 0) {
      toast.error(`${result.failed} file${result.failed === 1 ? "" : "s"} failed to move to trash`);
    }
    setDeleteRequest(null);
    setIsDeleting(false);
  };

  if (files.isLoading || folders.isLoading) return <DashboardSkeleton />;
  if (files.isError) {
    return (
      <EmptyState icon={HardDrive} title="Couldn't load your files" description="Try refreshing the page." />
    );
  }
  if (!insights || insights.totalFiles === 0) {
    return (
      <EmptyState icon={HardDrive} title="Nothing to analyze yet" description="Upload files to see storage insights." />
    );
  }

  const topFolders = insights.byTopFolder.map((b) => ({ ...b, mb: b.bytes / 1024 / 1024 }));
  const months = insights.byMonth.slice(-12);
  const showMonths = months.length > 1;
  const activeFilterLabel = filter.category ?? filter.topFolder;
  const largestTitle = activeFilterLabel ? `Largest files · ${activeFilterLabel}` : "Largest files";
  const duplicateExtrasCount = insights.duplicates.reduce(
    (total, group) => total + duplicateExtras(group).length,
    0,
  );
  const stalePreview = insights.stale.slice(0, 10);

  const requestDuplicateDeletion = (groups: DuplicateGroup[]) => {
    const extras = groups.flatMap(duplicateExtras);
    if (extras.length === 0) return;
    const bytes = extras.reduce((total, file) => total + file.size, 0);
    setDeleteRequest({
      ids: extras.map((file) => file.id),
      title: "Move extra copies to trash?",
      description: `Moves ${extras.length} extra ${extras.length === 1 ? "copy" : "copies"} (${formatFileSize(bytes)}) to trash and keeps the most recently updated copy of each. You can restore them from Trash.`,
    });
  };

  const requestStaleDeletion = () => {
    if (insights.stale.length === 0) return;
    const bytes = insights.stale.reduce((total, file) => total + file.size, 0);
    setDeleteRequest({
      ids: insights.stale.map((file) => file.id),
      title: "Move stale files to trash?",
      description: `Moves ${insights.stale.length} stale file${insights.stale.length === 1 ? "" : "s"} (${formatFileSize(bytes)}) to trash. You can restore them from Trash.`,
    });
  };

  return (
    <>
      <div className="max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Storage insights</h1>
        <p className="text-sm text-gray-500 mt-1">
          Where your space goes, what&apos;s gone stale, and what you could clean up.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Kpi icon={HardDrive} label="Storage used" value={formatFileSize(insights.totalBytes)}
          sub={`${insights.totalFiles.toLocaleString()} files`} color="bg-blue-50 text-blue-600" />
        <Kpi icon={PieIcon} label="Average file" value={formatFileSize(insights.averageBytes)}
          sub={`${insights.byCategory.length} file types`} color="bg-purple-50 text-purple-600" />
        <Kpi icon={Copy} label="Reclaimable from duplicates" value={formatFileSize(insights.reclaimableBytes)}
          sub={`${insights.duplicates.length.toLocaleString()} duplicate sets`} color="bg-orange-50 text-orange-600" />
        <Kpi icon={Hourglass} label={`Untouched ${STALE_AFTER_DAYS}+ days`} value={insights.staleFiles.toLocaleString()}
          sub={formatFileSize(insights.staleBytes)} color="bg-green-50 text-green-600" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <Panel title="By file type" className="lg:col-span-2">
          <div className="flex items-center gap-4">
            <ResponsiveContainer width="50%" height={220}>
              <PieChart>
                <Pie
                  data={insights.byCategory}
                  dataKey="bytes"
                  nameKey="category"
                  innerRadius={50}
                  outerRadius={90}
                  paddingAngle={1}
                  onClick={(entry, index) => {
                    const datum = entry as { category?: FileCategory; payload?: { category?: FileCategory } };
                    const category = datum.payload?.category ?? datum.category ?? insights.byCategory[index]?.category;
                    if (category) toggleCategoryFilter(category);
                  }}
                >
                  {insights.byCategory.map((c, i) => (
                    <Cell
                      key={c.category}
                      fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]}
                      fillOpacity={filter.category && filter.category !== c.category ? 0.25 : 1}
                    />
                  ))}
                </Pie>
                <Tooltip formatter={(v: number) => formatFileSize(v)} />
              </PieChart>
            </ResponsiveContainer>
            <ul className="flex-1 space-y-1.5 text-sm">
              {insights.byCategory.map((c, i) => (
                <li key={c.category}>
                  <button
                    type="button"
                    aria-pressed={filter.category === c.category}
                    onClick={() => toggleCategoryFilter(c.category)}
                    className={`flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-sm ${
                      filter.category === c.category ? "bg-otter-50" : "hover:bg-gray-50"
                    }`}
                  >
                    <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0"
                      style={{ background: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }} />
                    <span className="text-gray-700 flex-1 truncate">{c.category}</span>
                    <span className="text-gray-500 tabular-nums">{formatFileSize(c.bytes)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </Panel>

        <Panel title="By top-level folder" className="lg:col-span-3">
          <ResponsiveContainer width="100%" height={Math.max(220, topFolders.length * 24)}>
            <BarChart data={topFolders} layout="vertical" margin={{ left: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 11 }} unit=" MB" />
              <YAxis type="category" dataKey="label" width={130} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(_v, _n, item) => [
                `${formatFileSize(item.payload.bytes)} · ${item.payload.count} files`, "Size",
              ]} />
              <Bar
                dataKey="mb"
                fill="#2563eb"
                radius={[0, 4, 4, 0]}
                onClick={(entry) => {
                  const datum = entry as { label?: string; payload?: { label?: string } };
                  const label = datum.payload?.label ?? datum.label;
                  if (label) toggleFolderFilter(label);
                }}
              >
                {topFolders.map((folder) => (
                  <Cell
                    key={folder.label}
                    fillOpacity={filter.topFolder && filter.topFolder !== folder.label ? 0.25 : 1}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Panel>
      </div>

      <div className={`grid grid-cols-1 gap-6 ${showMonths ? "lg:grid-cols-2" : ""}`}>
        <Panel title="File size distribution">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={insights.bySize}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
              <Tooltip formatter={(_v, _n, item) => [
                `${item.payload.count.toLocaleString()} files · ${formatFileSize(item.payload.bytes)}`, "Files",
              ]} />
              <Bar dataKey="count" fill="#0891b2" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Panel>
        {showMonths && (
          <Panel title="Uploads by month">
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={months}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip formatter={(v: number) => [v.toLocaleString(), "Files uploaded"]} />
                <Bar dataKey="count" fill="#7c3aed" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Panel>
        )}
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-3">
        <Panel
          title={largestTitle}
          action={activeFilterLabel ? (
            <button
              type="button"
              onClick={() => setFilter({})}
              className="whitespace-nowrap rounded-md border border-gray-200 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
            >
              Clear filter
            </button>
          ) : undefined}
        >
          {largest.length === 0 && activeFilterLabel ? (
            <p className="py-6 text-center text-sm text-gray-500">No files match this filter.</p>
          ) : (
            <ul className="divide-y divide-gray-100">
              {largest.map((f) => (
                <li key={f.id} className="flex items-center gap-3 py-2 text-sm">
                  <FileText size={16} className="text-gray-400 flex-shrink-0" />
                  <Link to={`/files/${f.id}`} className="flex-1 truncate text-gray-800 hover:text-otter-600">
                    {f.name}
                  </Link>
                  <span className="text-gray-500 tabular-nums">{formatFileSize(f.size)}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel
          title="Duplicate files"
          action={duplicateExtrasCount > 0 ? (
            <button
              type="button"
              disabled={isDeleting}
              onClick={() => requestDuplicateDeletion(insights.duplicates)}
              className="rounded-md border border-gray-200 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Trash all extras ({duplicateExtrasCount})
            </button>
          ) : undefined}
        >
          {insights.duplicates.length === 0 ? (
            <p className="text-sm text-gray-500 py-6 text-center">No duplicates found.</p>
          ) : (
            <ul className="divide-y divide-gray-100">
              {insights.duplicates.slice(0, 10).map((d) => {
                const extras = duplicateExtras(d);
                const newest = d.files.find((file) => !extras.includes(file)) ?? d.files[0];
                return (
                  <li key={`${d.name}-${d.size}`} className="flex items-center gap-2 py-2 text-sm">
                    <Archive size={16} className="text-gray-400 flex-shrink-0" />
                    <Link to={`/files/${newest.id}`} className="flex-1 truncate text-gray-800 hover:text-otter-600">
                      {d.name}
                    </Link>
                    <span className="text-xs text-gray-500">{d.files.length} copies</span>
                    <span className="w-16 text-right text-gray-500 tabular-nums">
                      {formatFileSize(d.wastedBytes)}
                    </span>
                    <button
                      type="button"
                      disabled={isDeleting}
                      title="Move extra copies to trash"
                      aria-label="Move extra copies to trash"
                      onClick={() => requestDuplicateDeletion([d])}
                      className="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Trash2 size={14} />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          {insights.duplicates.length > 0 && (
            <p className="text-xs text-gray-400 mt-2">
              Matched by file name and size. Newest copy last updated{" "}
              {formatRelativeTime(
                insights.duplicates[0].files.find((file) => !duplicateExtras(insights.duplicates[0]).includes(file))!
                  .updatedAt,
              )}.
            </p>
          )}
        </Panel>

        <Panel
          title={`Stale files · ${STALE_AFTER_DAYS}+ days`}
          className="md:col-span-2 xl:col-span-1"
          action={insights.stale.length > 0 ? (
            <button
              type="button"
              disabled={isDeleting}
              onClick={requestStaleDeletion}
              className="rounded-md border border-gray-200 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Trash all ({insights.stale.length})
            </button>
          ) : undefined}
        >
          {insights.stale.length === 0 ? (
            <p className="py-6 text-center text-sm text-gray-500">
              Nothing untouched for {STALE_AFTER_DAYS}+ days.
            </p>
          ) : (
            <>
              <ul className="divide-y divide-gray-100">
                {stalePreview.map((f) => (
                  <li key={f.id} className="flex items-center gap-3 py-2 text-sm">
                    <Hourglass size={15} className="flex-shrink-0 text-gray-400" />
                    <div className="min-w-0 flex-1">
                      <Link to={`/files/${f.id}`} className="block truncate text-gray-800 hover:text-otter-600">
                        {f.name}
                      </Link>
                      <span className="text-xs text-gray-500">
                        updated {formatRelativeTime(f.updatedAt || f.createdAt)}
                      </span>
                    </div>
                    <span className="text-gray-500 tabular-nums">{formatFileSize(f.size)}</span>
                  </li>
                ))}
              </ul>
              {insights.stale.length > stalePreview.length && (
                <p className="mt-2 text-xs text-gray-400">+{insights.stale.length - stalePreview.length} more</p>
              )}
            </>
          )}
        </Panel>
      </div>
      </div>
      <ConfirmDialog
        open={deleteRequest !== null}
        title={deleteRequest?.title ?? ""}
        description={deleteRequest?.description ?? ""}
        confirmLabel="Move to trash"
        variant="destructive"
        isBusy={isDeleting}
        onConfirm={confirmDeletion}
        onCancel={() => {
          if (!isDeleting) setDeleteRequest(null);
        }}
      />
    </>
  );
}

function Kpi({
  icon: Icon,
  label,
  value,
  sub,
  color,
}: Readonly<{ icon: typeof HardDrive; label: string; value: string; sub: string; color: string }>) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-center gap-3">
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${color}`}>
          <Icon size={20} />
        </div>
        <div className="min-w-0">
          <p className="text-2xl font-bold text-gray-900">{value}</p>
          <p className="text-xs text-gray-600 truncate">{label}</p>
          <p className="text-xs text-gray-400 truncate">{sub}</p>
        </div>
      </div>
    </div>
  );
}

function Panel({
  title,
  className = "",
  action,
  children,
}: Readonly<{ title: string; className?: string; action?: React.ReactNode; children: React.ReactNode }>) {
  return (
    <section className={`bg-white rounded-xl border border-gray-200 p-5 ${className}`}>
      <div className="mb-3 flex min-h-5 items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}
