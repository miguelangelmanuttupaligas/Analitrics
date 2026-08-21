import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Constants, QueryKeys, dataService } from 'librechat-data-provider';

export type AnalitricsFile = {
  file_id?: string;
  filename?: string;
  storageKey?: string;
  mimeType?: string;
  bytes?: number;
};

export type AnalitricsColumn =
  | string
  | {
      name?: string;
      type?: string;
      nullable?: boolean;
      sample?: unknown;
    };

export type AnalitricsTable = {
  table?: string;
  sourceFileId?: string;
  sourceFilename?: string;
  rowCount?: number;
  columns?: AnalitricsColumn[];
  systemTable?: boolean;
  updatedAt?: string | null;
};

export type AnalitricsProfile = {
  table?: string;
  row_count?: number;
  columns?: AnalitricsColumn[];
  source_file_id?: string | null;
  source_filename?: string | null;
  system_table?: boolean;
};

export type AnalitricsContextSummary = {
  fileCount?: number;
  tableCount?: number;
  rowCountTotal?: number;
  cachePath?: string | null;
};

export type AnalitricsFeedback = {
  feedbackId?: string;
  sourceFileId?: string | null;
  sourceFilename?: string | null;
  step: number;
  label: string;
  content: string;
  createdAt?: string | null;
  updatedAt?: string | null;
};

export type AnalitricsContext = {
  ok?: boolean;
  found?: boolean;
  tenantId?: string;
  userId?: string;
  conversationId?: string;
  cachePath?: string | null;
  cacheHits?: number | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  files?: AnalitricsFile[];
  tables?: AnalitricsTable[];
  profiles?: AnalitricsProfile[];
  feedback?: AnalitricsFeedback[];
  summary?: AnalitricsContextSummary;
};

const isValidConversationId = (conversationId?: string | null) =>
  Boolean(
    conversationId &&
      conversationId !== Constants.NEW_CONVO &&
      conversationId !== Constants.PENDING_CONVO &&
      conversationId !== Constants.SEARCH,
  );

export default function useAnalitricsContext(conversationId?: string | null) {
  return useQuery<AnalitricsContext>(
    [QueryKeys.analitricsContext, conversationId],
    () => dataService.getAnalitricsContext<AnalitricsContext>(conversationId ?? ''),
    {
      enabled: isValidConversationId(conversationId),
      refetchOnMount: true,
      refetchOnReconnect: true,
      refetchOnWindowFocus: false,
      staleTime: 10_000,
    },
  );
}

export function useSaveAnalitricsCatalogFeedback(conversationId?: string | null) {
  const queryClient = useQueryClient();

  return useMutation(
    (payload: {
      sourceFileId?: string | null;
      sourceFilename?: string | null;
      step: number;
      label: string;
      content: string;
    }) =>
      dataService.saveAnalitricsCatalogFeedback({
        conversationId: conversationId ?? '',
        ...payload,
      }),
    {
      onSuccess: () => {
        queryClient.invalidateQueries([QueryKeys.analitricsContext, conversationId]);
      },
    },
  );
}
