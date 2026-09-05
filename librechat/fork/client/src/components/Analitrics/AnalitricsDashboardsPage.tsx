import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { AlertCircle, BarChart3, RefreshCw, SendHorizontal } from 'lucide-react';
import { Spinner } from '@librechat/client';
import {
  useApplyAnalitricsDashboardInstruction,
  useAnalitricsDashboard,
  useAnalitricsDashboards,
  useDocumentTitle,
  useLocalize,
  useRunAnalitricsDashboardView,
} from '~/hooks';
import type { AnalitricsDashboardView } from '~/hooks';
import OpenSidebar from '~/components/Chat/Menus/OpenSidebar';
import AnalitricsEChart from './AnalitricsEChart';
import { cn } from '~/utils';

function formatDate(value: string | null | undefined, localize: ReturnType<typeof useLocalize>) {
  if (!value) {
    return localize('com_analitrics_no_date');
  }
  return new Intl.DateTimeFormat('es-PE', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="flex min-h-64 flex-col items-center justify-center rounded-lg border border-border-light bg-surface-primary p-6 text-center">
      <BarChart3 className="size-8 text-text-tertiary" aria-hidden="true" />
      <h2 className="mt-3 text-base font-semibold text-text-primary">{title}</h2>
      <p className="mt-1 max-w-md text-sm text-text-secondary">{detail}</p>
    </div>
  );
}

function DashboardChartCard({
  dashboardId,
  view,
  localize,
}: {
  dashboardId: string;
  view: AnalitricsDashboardView;
  localize: ReturnType<typeof useLocalize>;
}) {
  const runQuery = useRunAnalitricsDashboardView(dashboardId, view.viewId);

  return (
    <section className="min-w-0 rounded-lg border border-border-light bg-surface-primary p-4">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-base font-semibold">
            {view.title || localize('com_analitrics_dashboard_chart_fallback')}
          </h3>
          {view.question && (
            <p className="mt-1 line-clamp-2 text-sm text-text-secondary">
              {view.question}
            </p>
          )}
        </div>
        <BarChart3 className="size-5 shrink-0 text-text-tertiary" aria-hidden="true" />
      </div>
      {runQuery.isLoading ? (
        <div className="flex min-h-40 items-center justify-center gap-2 text-sm text-text-secondary">
          <Spinner className="size-4" />
          {localize('com_analitrics_dashboard_chart_running')}
        </div>
      ) : runQuery.isError ? (
        <div className="rounded-lg border border-status-error-border bg-surface-secondary p-3 text-sm text-text-primary">
          {localize('com_analitrics_dashboard_chart_run_error')}
        </div>
      ) : view.chartSpec?.renderer === 'echarts' ? (
        <AnalitricsEChart spec={view.chartSpec} rows={runQuery.data?.rows ?? []} />
      ) : (
        <div className="rounded-lg border border-border-light bg-surface-secondary p-4 text-sm text-text-secondary">
          {localize('com_analitrics_dashboard_chart_invalid')}
        </div>
      )}
    </section>
  );
}

function DashboardInstructionBox({
  dashboardId,
  localize,
}: {
  dashboardId: string;
  localize: ReturnType<typeof useLocalize>;
}) {
  const [instruction, setInstruction] = useState('');
  const applyInstruction = useApplyAnalitricsDashboardInstruction(dashboardId);
  const lastOperation = applyInstruction.data?.lastOperation;
  const detail =
    typeof lastOperation?.changed === 'string'
      ? lastOperation.changed
      : typeof lastOperation?.reason === 'string'
        ? lastOperation.reason
        : '';

  return (
    <section className="rounded-lg border border-border-light bg-surface-primary p-4">
      <div className="mb-3">
        <h3 className="text-base font-semibold">{localize('com_analitrics_dashboard_adjust_title')}</h3>
        <p className="mt-1 text-sm text-text-secondary">
          {localize('com_analitrics_dashboard_adjust_detail')}
        </p>
      </div>
      <form
        className="flex flex-col gap-2 sm:flex-row"
        onSubmit={(event) => {
          event.preventDefault();
          const value = instruction.trim();
          if (!value || applyInstruction.isLoading) {
            return;
          }
          applyInstruction.mutate(
            { instruction: value },
            {
              onSuccess: () => setInstruction(''),
            },
          );
        }}
      >
        <input
          className="min-h-10 flex-1 rounded-lg border border-border-light bg-surface-secondary px-3 text-sm text-text-primary outline-none transition-colors placeholder:text-text-tertiary focus:border-border-heavy"
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          placeholder={localize('com_analitrics_dashboard_adjust_placeholder')}
        />
        <button
          type="submit"
          disabled={!instruction.trim() || applyInstruction.isLoading}
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-text-primary px-4 text-sm font-medium text-surface-primary transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
        >
          {applyInstruction.isLoading ? (
            <Spinner className="size-4" />
          ) : (
            <SendHorizontal className="size-4" aria-hidden="true" />
          )}
          {localize('com_analitrics_dashboard_adjust_action')}
        </button>
      </form>
      {applyInstruction.isError && (
        <p className="mt-3 text-sm text-status-error">
          {localize('com_analitrics_dashboard_adjust_error')}
        </p>
      )}
      {detail && (
        <p className="mt-3 rounded-lg border border-border-light bg-surface-secondary px-3 py-2 text-sm text-text-secondary">
          {detail}
        </p>
      )}
    </section>
  );
}

export default function AnalitricsDashboardsPage() {
  const localize = useLocalize();
  useDocumentTitle(`${localize('com_analitrics_dashboard_title')} | Analitrics`);
  const navigate = useNavigate();
  const { dashboardId } = useParams();
  const dashboardsQuery = useAnalitricsDashboards();
  const dashboards = dashboardsQuery.data?.dashboards ?? [];
  const effectiveDashboardId = dashboardId || dashboards[0]?.dashboardId || null;
  const dashboardQuery = useAnalitricsDashboard(effectiveDashboardId);
  const dashboard = dashboardQuery.data?.dashboard;
  const views = dashboard?.views ?? [];

  useEffect(() => {
    if (!dashboardId && dashboards[0]?.dashboardId) {
      navigate(`/dashboards/${dashboards[0].dashboardId}`, { replace: true });
    }
  }, [dashboardId, dashboards, navigate]);

  return (
    <main className="flex h-full min-h-0 flex-col bg-surface-primary text-text-primary">
      <header className="flex shrink-0 items-center gap-3 border-b border-border-light px-4 py-3">
        <OpenSidebar className="size-9 shrink-0" />
        <div className="min-w-0 flex-1">
          <h1 className="text-lg font-semibold">{localize('com_analitrics_dashboard_title')}</h1>
          <p className="text-sm text-text-secondary">{localize('com_analitrics_dashboard_subtitle')}</p>
        </div>
        <button
          type="button"
          className="rounded-lg p-2 text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary"
          onClick={() => {
            dashboardsQuery.refetch();
            dashboardQuery.refetch();
          }}
          aria-label={localize('com_analitrics_dashboard_refresh')}
        >
          <RefreshCw
            className={cn('size-4', (dashboardsQuery.isFetching || dashboardQuery.isFetching) && 'animate-spin')}
            aria-hidden="true"
          />
        </button>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[minmax(16rem,22rem)_1fr]">
        <aside className="min-h-0 overflow-y-auto border-b border-border-light bg-surface-primary-alt p-3 lg:border-b-0 lg:border-r">
          <h2 className="mb-2 px-2 text-xs font-semibold uppercase text-text-secondary">
            {localize('com_analitrics_dashboard_my_dashboards')}
          </h2>
          {dashboardsQuery.isLoading ? (
            <div className="flex items-center gap-2 px-2 py-4 text-sm text-text-secondary">
              <Spinner className="size-4" />
              {localize('com_analitrics_dashboard_loading')}
            </div>
          ) : dashboards.length === 0 ? (
            <p className="px-2 py-4 text-sm text-text-secondary">
              {localize('com_analitrics_dashboard_empty_list')}
            </p>
          ) : (
            <div className="space-y-1">
              {dashboards.map((item) => {
                const active = item.dashboardId === effectiveDashboardId;
                return (
                  <Link
                    key={item.dashboardId}
                    to={`/dashboards/${item.dashboardId}`}
                    className={cn(
                      'block rounded-lg border p-3 transition-colors',
                      active
                        ? 'border-border-heavy bg-surface-secondary text-text-primary'
                        : 'border-transparent text-text-secondary hover:bg-surface-hover hover:text-text-primary',
                    )}
                  >
                    <div className="line-clamp-2 text-sm font-medium">{item.title}</div>
                    <div className="mt-2 text-xs text-text-tertiary">
                      {formatDate(item.updatedAt, localize)}
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </aside>

        <section className="min-h-0 overflow-y-auto p-4">
          {!effectiveDashboardId && (
            <EmptyState
              title={localize('com_analitrics_dashboard_empty_title')}
              detail={localize('com_analitrics_dashboard_empty_detail')}
            />
          )}

          {dashboardQuery.isError && (
            <div className="flex gap-2 rounded-lg border border-status-error-border bg-surface-secondary p-4 text-sm">
              <AlertCircle className="mt-0.5 size-4 shrink-0 text-status-error" aria-hidden="true" />
              <span>{localize('com_analitrics_dashboard_load_error')}</span>
            </div>
          )}

          {dashboard && (
            <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
              <section className="rounded-lg border border-border-light bg-surface-primary p-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div className="min-w-0">
                    <h2 className="text-xl font-semibold">{dashboard.title}</h2>
                    <p className="mt-1 line-clamp-2 text-sm text-text-secondary">
                      {dashboard.seedQuestion}
                    </p>
                  </div>
                  <Link
                    to={`/c/${dashboard.conversationId}`}
                    className="shrink-0 rounded-lg border border-border-light px-3 py-2 text-sm font-medium text-text-primary transition-colors hover:bg-surface-hover"
                  >
                    {localize('com_analitrics_dashboard_open_chat')}
                  </Link>
                </div>
              </section>

              <DashboardInstructionBox dashboardId={dashboard.dashboardId} localize={localize} />

              {views.length === 0 ? (
                <EmptyState
                  title={localize('com_analitrics_dashboard_no_charts_title')}
                  detail={localize('com_analitrics_dashboard_no_charts_detail')}
                />
              ) : (
                <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                  {views.map((view) => (
                    <DashboardChartCard
                      key={view.viewId}
                      dashboardId={dashboard.dashboardId}
                      view={view}
                      localize={localize}
                    />
                  ))}
                </div>
              )}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
