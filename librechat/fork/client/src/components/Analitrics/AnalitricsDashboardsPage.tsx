import { useEffect } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { AlertCircle, BarChart3, RefreshCw } from 'lucide-react';
import { Spinner } from '@librechat/client';
import {
  useAnalitricsDashboard,
  useAnalitricsDashboards,
  useDocumentTitle,
  useRunAnalitricsDashboardView,
} from '~/hooks';
import OpenSidebar from '~/components/Chat/Menus/OpenSidebar';
import AnalitricsEChart from './AnalitricsEChart';
import { cn } from '~/utils';

function formatDate(value?: string | null) {
  if (!value) {
    return 'Sin fecha';
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

export default function AnalitricsDashboardsPage() {
  useDocumentTitle('Dashboards | Analitrics');
  const navigate = useNavigate();
  const { dashboardId } = useParams();
  const dashboardsQuery = useAnalitricsDashboards();
  const dashboards = dashboardsQuery.data?.dashboards ?? [];
  const effectiveDashboardId = dashboardId || dashboards[0]?.dashboardId || null;
  const dashboardQuery = useAnalitricsDashboard(effectiveDashboardId);
  const dashboard = dashboardQuery.data?.dashboard;
  const views = dashboard?.views ?? [];
  const chartView = views.find((view) => view.chartSpec?.renderer === 'echarts') ?? views[0];
  const runQuery = useRunAnalitricsDashboardView(dashboard?.dashboardId, chartView?.viewId);

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
          <h1 className="text-lg font-semibold">Dashboards</h1>
          <p className="text-sm text-text-secondary">
            Gráficos privados creados desde análisis conversacionales.
          </p>
        </div>
        <button
          type="button"
          className="rounded-lg p-2 text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary"
          onClick={() => {
            dashboardsQuery.refetch();
            dashboardQuery.refetch();
            runQuery.refetch();
          }}
          aria-label="Actualizar dashboards"
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
            Mis dashboards
          </h2>
          {dashboardsQuery.isLoading ? (
            <div className="flex items-center gap-2 px-2 py-4 text-sm text-text-secondary">
              <Spinner className="size-4" />
              Cargando
            </div>
          ) : dashboards.length === 0 ? (
            <p className="px-2 py-4 text-sm text-text-secondary">
              Aún no creaste dashboards desde un análisis.
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
                    <div className="mt-2 text-xs text-text-tertiary">{formatDate(item.updatedAt)}</div>
                  </Link>
                );
              })}
            </div>
          )}
        </aside>

        <section className="min-h-0 overflow-y-auto p-4">
          {!effectiveDashboardId && (
            <EmptyState
              title="Sin dashboards"
              detail="Cuando tengas una respuesta analítica útil en un chat, créala como dashboard desde el panel derecho."
            />
          )}

          {dashboardQuery.isError && (
            <div className="flex gap-2 rounded-lg border border-status-error-border bg-surface-secondary p-4 text-sm">
              <AlertCircle className="mt-0.5 size-4 shrink-0 text-status-error" aria-hidden="true" />
              <span>No se pudo cargar el dashboard.</span>
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
                    Abrir chat
                  </Link>
                </div>
              </section>

              <section className="min-w-0 rounded-lg border border-border-light bg-surface-primary p-4">
                <div className="mb-4 flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="text-base font-semibold">{chartView?.title ?? 'Grafico'}</h3>
                    <p className="mt-1 line-clamp-2 text-sm text-text-secondary">
                      {chartView?.question ?? dashboard.seedQuestion}
                    </p>
                  </div>
                  <BarChart3 className="size-5 shrink-0 text-text-tertiary" aria-hidden="true" />
                </div>
                {runQuery.isLoading ? (
                  <div className="flex min-h-40 items-center justify-center gap-2 text-sm text-text-secondary">
                    <Spinner className="size-4" />
                    Ejecutando gráfico
                  </div>
                ) : runQuery.isError ? (
                  <div className="rounded-lg border border-status-error-border bg-surface-secondary p-3 text-sm text-text-primary">
                    No se pudo ejecutar el gráfico.
                  </div>
                ) : chartView?.chartSpec?.renderer === 'echarts' ? (
                  <AnalitricsEChart spec={chartView.chartSpec} rows={runQuery.data?.rows ?? []} />
                ) : (
                  <div className="rounded-lg border border-border-light bg-surface-secondary p-4 text-sm text-text-secondary">
                    Este dashboard todavía no tiene un gráfico válido.
                  </div>
                )}
              </section>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
