import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { QueryKeys, dataService } from 'librechat-data-provider';

export type AnalitricsDashboardSummary = {
  dashboardId: string;
  conversationId: string;
  title: string;
  description?: string | null;
  seedQuestion?: string | null;
  sourceFileIds?: string[];
  createdAt?: string | null;
  updatedAt?: string | null;
};

export type AnalitricsDashboardView = {
  viewId: string;
  title: string;
  viewType: 'table' | 'bar' | 'line' | 'pie' | 'kpi' | string;
  question?: string | null;
  sql: string;
  chartSpec?: Record<string, unknown>;
  position?: number;
  createdAt?: string | null;
  updatedAt?: string | null;
};

export type AnalitricsDashboard = AnalitricsDashboardSummary & {
  seedSql?: string;
  seedMessageId?: string | null;
  seedRunId?: string | null;
  duckdbPath?: string | null;
  catalogSnapshot?: {
    summary?: { fileCount?: number; tableCount?: number; rowCountTotal?: number };
    files?: Array<{ filename?: string; file_id?: string }>;
    tables?: Array<{ table?: string; sourceFilename?: string; rowCount?: number }>;
  };
  businessContext?: Record<string, unknown>;
  views?: AnalitricsDashboardView[];
};

export type AnalitricsDashboardRun = {
  ok?: boolean;
  columns?: string[];
  rows?: Array<Record<string, unknown>>;
  rowCount?: number;
  limit?: number;
};

export function useAnalitricsDashboards() {
  return useQuery<{ ok?: boolean; dashboards?: AnalitricsDashboardSummary[] }>(
    [QueryKeys.analitricsDashboards],
    () => dataService.listAnalitricsDashboards(),
    {
      refetchOnWindowFocus: false,
      staleTime: 15_000,
    },
  );
}

export function useAnalitricsDashboard(dashboardId?: string | null) {
  return useQuery<{ ok?: boolean; dashboard?: AnalitricsDashboard }>(
    [QueryKeys.analitricsDashboard, dashboardId],
    () => dataService.getAnalitricsDashboard(dashboardId ?? ''),
    {
      enabled: Boolean(dashboardId),
      refetchOnWindowFocus: false,
      staleTime: 15_000,
    },
  );
}

export function useCreateAnalitricsDashboardFromAnalysis() {
  const queryClient = useQueryClient();
  return useMutation(
    (payload: { conversationId: string; title?: string }) =>
      dataService.createAnalitricsDashboardFromAnalysis<{ ok?: boolean; dashboard?: AnalitricsDashboard }>(
        payload,
      ),
    {
      onSuccess: () => {
        queryClient.invalidateQueries([QueryKeys.analitricsDashboards]);
      },
    },
  );
}

export function useRunAnalitricsDashboardView(dashboardId?: string | null, viewId?: string | null) {
  return useQuery<AnalitricsDashboardRun>(
    [QueryKeys.analitricsDashboard, dashboardId, 'view', viewId],
    () => dataService.runAnalitricsDashboardView(dashboardId ?? '', viewId ?? '', { limit: 200 }),
    {
      enabled: Boolean(dashboardId && viewId),
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  );
}
