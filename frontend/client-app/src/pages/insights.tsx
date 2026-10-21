import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Archive, Copy, FileText, HardDrive, Hourglass, PieChart as PieIcon } from "lucide-react";
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
import { DashboardSkeleton } from "@/components/ui/skeleton";
import { filesApi } from "@/lib/api";
import { computeInsights, STALE_AFTER_DAYS } from "@/lib/insights";
import { formatFileSize, formatRelativeTime } from "@/lib/utils";

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

  const insights = useMemo(
    () =>
      files.data
        ? computeInsights(
            files.data,
            (folders.data ?? []).map((f) => ({ id: f.id, name: f.name, parentId: f.parentId })),
          )
        : null,
    [files.data, folders.data],
  );

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

  return (
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
                <Pie data={insights.byCategory} dataKey="bytes" nameKey="category" innerRadius={50} outerRadius={90} paddingAngle={1}>
                  {insights.byCategory.map((c, i) => (
                    <Cell key={c.category} fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(v: number) => formatFileSize(v)} />
              </PieChart>
            </ResponsiveContainer>
            <ul className="flex-1 space-y-1.5 text-sm">
              {insights.byCategory.map((c, i) => (
                <li key={c.category} className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0"
                    style={{ background: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }} />
                  <span className="text-gray-700 flex-1 truncate">{c.category}</span>
                  <span className="text-gray-500 tabular-nums">{formatFileSize(c.bytes)}</span>
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
              <Bar dataKey="mb" fill="#2563eb" radius={[0, 4, 4, 0]} />
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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Panel title="Largest files">
          <ul className="divide-y divide-gray-100">
            {insights.largest.map((f) => (
              <li key={f.id} className="flex items-center gap-3 py-2 text-sm">
                <FileText size={16} className="text-gray-400 flex-shrink-0" />
                <Link to={`/files/${f.id}`} className="flex-1 truncate text-gray-800 hover:text-otter-600">
                  {f.name}
                </Link>
                <span className="text-gray-500 tabular-nums">{formatFileSize(f.size)}</span>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Duplicate files">
          {insights.duplicates.length === 0 ? (
            <p className="text-sm text-gray-500 py-6 text-center">No duplicates found.</p>
          ) : (
            <ul className="divide-y divide-gray-100">
              {insights.duplicates.slice(0, 10).map((d) => (
                <li key={`${d.name}-${d.size}`} className="flex items-center gap-3 py-2 text-sm">
                  <Archive size={16} className="text-gray-400 flex-shrink-0" />
                  <Link to={`/files/${d.files[0].id}`} className="flex-1 truncate text-gray-800 hover:text-otter-600">
                    {d.name}
                  </Link>
                  <span className="text-xs text-gray-500">{d.files.length} copies</span>
                  <span className="text-gray-500 tabular-nums w-20 text-right">
                    {formatFileSize(d.wastedBytes)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {insights.duplicates.length > 0 && (
            <p className="text-xs text-gray-400 mt-2">
              Matched by file name and size. Newest copy last updated{" "}
              {formatRelativeTime(insights.duplicates[0].files.at(-1)!.updatedAt)}.
            </p>
          )}
        </Panel>
      </div>
    </div>
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
  children,
}: Readonly<{ title: string; className?: string; children: React.ReactNode }>) {
  return (
    <section className={`bg-white rounded-xl border border-gray-200 p-5 ${className}`}>
      <h2 className="text-sm font-semibold text-gray-900 mb-3">{title}</h2>
      {children}
    </section>
  );
}
