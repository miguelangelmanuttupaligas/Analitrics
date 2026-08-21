import { useMemo, useState, memo } from 'react';
import { useDefaultLayout } from 'react-resizable-panels';
import {
  ResizableHandleAlt,
  ResizablePanel,
  ResizablePanelGroup,
  useMediaQuery,
} from '@librechat/client';
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
  const [shouldRenderArtifacts, setShouldRenderArtifacts] = useState(artifacts != null);
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
            <ResizableHandleAlt withHandle className="bg-border-medium text-text-primary" />
            <ResizablePanel
              defaultSize="24"
              minSize="20"
              maxSize="34"
              collapsible={true}
              collapsedSize="0"
              id="analitrics-panel"
            >
              <div className="h-full min-w-[300px] overflow-hidden border-l border-border-light bg-surface-primary">
                {analitricsPanel}
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
