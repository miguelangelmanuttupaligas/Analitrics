import { cloneElement, isValidElement, useCallback, useMemo, useState, memo } from 'react';
import type { ReactElement } from 'react';
import { useDefaultLayout, usePanelRef } from 'react-resizable-panels';
import {
  Button,
  ResizableHandleAlt,
  ResizablePanel,
  ResizablePanelGroup,
  Sidebar,
  TooltipAnchor,
  useMediaQuery,
} from '@librechat/client';
import { useLocalize } from '~/hooks';
import ArtifactsPanel from './ArtifactsPanel';

const PANEL_IDS_SINGLE = ['messages-view'];
const PANEL_IDS_SPLIT = ['messages-view', 'artifacts-panel'];
const PANEL_IDS_ANALITRICS = ['messages-view', 'analitrics-panel'];
const PANEL_IDS_SPLIT_ANALITRICS = ['messages-view', 'artifacts-panel', 'analitrics-panel'];

interface SidePanelProps {
  artifacts?: React.ReactNode;
  analitricsPanel?: React.ReactNode;
  children: React.ReactNode;
}

const SidePanelGroup = memo(({ artifacts, analitricsPanel, children }: SidePanelProps) => {
  const localize = useLocalize();
  const [shouldRenderArtifacts, setShouldRenderArtifacts] = useState(artifacts != null);
  const [isAnalitricsCollapsed, setIsAnalitricsCollapsed] = useState(false);
  const analitricsPanelRef = usePanelRef();
  const isSmallScreen = useMediaQuery('(max-width: 767px)');
  const hasAnalitricsPanel = analitricsPanel != null;
  const panelIds = useMemo(() => {
    if (artifacts != null && hasAnalitricsPanel) {
      return PANEL_IDS_SPLIT_ANALITRICS;
    }
    if (artifacts != null) {
      return PANEL_IDS_SPLIT;
    }
    if (hasAnalitricsPanel) {
      return PANEL_IDS_ANALITRICS;
    }
    return PANEL_IDS_SINGLE;
  }, [artifacts, hasAnalitricsPanel]);

  const { defaultLayout, onLayoutChanged } = useDefaultLayout({
    id: 'side-panel-layout',
    panelIds,
    storage: localStorage,
  });

  const minSizeMain = artifacts != null || hasAnalitricsPanel ? '15' : '30';

  const handleCollapseAnalitrics = useCallback(() => {
    setIsAnalitricsCollapsed(true);
    analitricsPanelRef.current?.collapse();
  }, [analitricsPanelRef]);

  const handleExpandAnalitrics = useCallback(() => {
    setIsAnalitricsCollapsed(false);
    requestAnimationFrame(() => {
      analitricsPanelRef.current?.expand();
    });
  }, [analitricsPanelRef]);

  const analitricsPanelWithControls = useMemo(() => {
    if (!analitricsPanel || !hasAnalitricsPanel) {
      return analitricsPanel;
    }
    if (!isValidElement(analitricsPanel)) {
      return analitricsPanel;
    }
    return cloneElement(analitricsPanel as ReactElement<any>, {
      onCollapsePanel: handleCollapseAnalitrics,
    });
  }, [
    analitricsPanel,
    handleCollapseAnalitrics,
    hasAnalitricsPanel,
  ]);

  return (
    <>
      <ResizablePanelGroup
        orientation="horizontal"
        defaultLayout={defaultLayout}
        onLayoutChanged={onLayoutChanged}
        className="relative flex-1 bg-presentation"
      >
        <ResizablePanel defaultSize="50" minSize={minSizeMain} id="messages-view">
          {children}
        </ResizablePanel>

        {!isSmallScreen && (
          <ArtifactsPanel
            artifacts={artifacts}
            minSizeMain={minSizeMain}
            shouldRender={shouldRenderArtifacts}
            onRenderChange={setShouldRenderArtifacts}
          />
        )}

        {!isSmallScreen && hasAnalitricsPanel && (
          <>
            {!isAnalitricsCollapsed && (
              <ResizableHandleAlt withHandle className="bg-border-medium text-text-primary" />
            )}
            {isAnalitricsCollapsed && (
              <div className="flex h-full w-12 shrink-0 items-start justify-center border-l border-border-light bg-surface-primary-alt px-1.5 py-2">
                <TooltipAnchor
                  side="left"
                  description={localize('com_analitrics_open_side_panel')}
                  render={
                    <Button
                      size="icon"
                      variant="outline"
                      aria-label={localize('com_analitrics_open_side_panel')}
                      aria-expanded={false}
                      className="h-9 w-9 rounded-lg border-border-medium bg-text-primary text-surface-primary shadow-sm hover:bg-text-primary/90"
                      onClick={handleExpandAnalitrics}
                    >
                      <Sidebar aria-hidden="true" className="h-5 w-5" />
                    </Button>
                  }
                />
              </div>
            )}
            <ResizablePanel
              defaultSize="24"
              minSize="20"
              maxSize="34"
              collapsible={true}
              collapsedSize="0"
              panelRef={analitricsPanelRef}
              id="analitrics-panel"
              onCollapse={() => setIsAnalitricsCollapsed(true)}
              onExpand={() => setIsAnalitricsCollapsed(false)}
            >
              <div className="h-full min-w-[300px] overflow-hidden border-l border-border-light bg-surface-primary">
                {analitricsPanelWithControls}
              </div>
            </ResizablePanel>
          </>
        )}
      </ResizablePanelGroup>
      {artifacts != null && isSmallScreen && (
        <div className="fixed inset-0 z-[100]">{artifacts}</div>
      )}
    </>
  );
});

SidePanelGroup.displayName = 'SidePanelGroup';

export default SidePanelGroup;
