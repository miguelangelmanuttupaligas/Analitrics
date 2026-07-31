export type LibreChatAttachment = {
  file_id: string;
  filename: string;
  filepath: string;
  type: string;
  bytes?: number;
  user?: string;
  createdAt?: Date;
};

export type LibreChatMessage = {
  messageId: string;
  conversationId: string;
  createdAt?: Date;
  files?: LibreChatAttachment[];
  text?: string;
  isCreatedByUser?: boolean;
};

export type DiscoveredAttachment = {
  userId: string;
  conversationId: string;
  messageId: string;
  fileId: string;
  filename: string;
  mimeType: string;
  filepath: string;
  absolutePath: string;
  bytes: number;
};

export type InferredColumn = {
  sourceName: string;
  columnName: string;
  pgType: 'boolean' | 'bigint' | 'numeric' | 'timestamptz' | 'text';
  nullCount: number;
  sampleValues: Array<string | number | boolean | null>;
};

export type ParsedSheet = {
  sheetName: string;
  rows: Record<string, unknown>[];
  columns: InferredColumn[];
};

export type ImportedContext = {
  uploadId: string;
  filename: string;
  conversationId: string;
  summary: string;
  businessSummary: string;
  tables: Array<{
    sheetName: string;
    tableName: string;
    rowCount: number;
    columnCount: number;
  }>;
};

export type ContextTableProfile = {
  sheetName: string;
  tableName: string;
  rowCount: number;
  columnCount: number;
  columns: Array<{
    sourceName: string;
    columnName: string;
    pgType: string;
    nullCount: number;
    sampleValues: Array<string | number | boolean | null>;
  }>;
  sampleRows: Record<string, unknown>[];
};

export type ContextAssetProfile = {
  uploadId: string;
  filename: string;
  conversationId: string;
  summary: string;
  businessSummary: string;
  tables: ContextTableProfile[];
};

export type ContextAssetSummary = {
  uploadId: string;
  filename: string;
  conversationId: string;
  summary: string;
  businessSummary: string;
  tableCount: number;
  totalRows: number;
  totalColumns: number;
  matchedBy: string[];
  recencyRank: number;
  score: number;
  tables: ContextTableProfile[];
};

export type ContextAttachmentSummary = {
  available: boolean;
  fileId: string;
  filename: string;
  conversationId: string;
  mimeType: string;
  imported: boolean;
};

export type ContextBudget = {
  maxAssets: number;
  maxTablesPerAsset: number;
  maxColumnsPerTable: number;
  maxSampleRowsPerTable: number;
};

export type ContextSnapshot = {
  userId: string;
  conversationId?: string;
  filenameHint?: string;
  budget: ContextBudget;
  selectedAssets: ContextAssetSummary[];
  availableAssets: Array<{
    uploadId: string;
    filename: string;
    conversationId: string;
    summary: string;
    businessSummary: string;
    tableCount: number;
    totalRows: number;
    totalColumns: number;
    recencyRank: number;
  }>;
  recentAttachments: ContextAttachmentSummary[];
  activeFile: {
    available: boolean;
    filename?: string;
    summary?: string;
    businessSummary?: string;
    uploadId?: string;
    tables: ContextTableProfile[];
  };
  latestAttachment: {
    available: boolean;
    filename?: string;
    conversationId?: string;
  };
  corporateTables: Array<{
    schema: string;
    table: string;
  }>;
};

export type AnalyticsIntent = {
  intent:
    | 'resumen'
    | 'hallazgos'
    | 'calidad'
    | 'conteo'
    | 'columnas'
    | 'tabla'
    | 'grafico'
    | 'comparacion'
    | 'pregunta_gerencial'
    | 'ambigua'
    | 'otro';
  outputMode: 'texto' | 'tabla' | 'grafico' | 'aclaracion';
  dataScope: 'archivo' | 'corporativo' | 'combinado' | 'indefinido';
  needsActiveFile: boolean;
  shouldAskClarifyingQuestion: boolean;
  clarificationQuestion: string;
  chartType: 'barras' | 'lineas' | 'torta' | 'tabla' | 'ninguno';
  orientation: 'horizontal' | 'vertical' | 'ninguna';
  confidence: number;
  rationale: string;
};

export type CleanedQuestion = {
  cleanedQuestion: string;
  userGoal: string;
  requestedOutput: 'texto' | 'tabla' | 'grafico' | 'aclaracion';
  businessTone: 'ejecutivo' | 'analitico' | 'operativo' | 'neutro';
  mentionedEntities: string[];
  ambiguityNotes: string[];
};

export type AnalyticsPlan = {
  objective: string;
  responseMode: 'texto' | 'tabla' | 'grafico' | 'aclaracion';
  dataSource: 'archivo' | 'corporativo' | 'combinado' | 'ninguno';
  ensureImport: boolean;
  useContextSummary: boolean;
  sql: string;
  title: string;
  chartType: 'barras' | 'lineas' | 'torta' | 'tabla' | 'ninguno';
  labelColumn: string;
  valueColumn: string;
  orientation: 'horizontal' | 'vertical' | 'ninguna';
  xField: string;
  yField: string;
  colorField: string;
  topN: number | null;
  clarificationQuestion: string;
  successCriteria: string[];
  riskNotes: string[];
};

export type AnalyticsSourceSelection = {
  mode: 'archivo' | 'corporativo' | 'combinado' | 'ninguno';
  rationale: string;
  needsClarification: boolean;
  clarificationQuestion: string;
};

export type GraphNodeTrace = {
  node: string;
  startedAt: string;
  completedAt: string;
  elapsedMs: number;
  status: 'ok' | 'error';
  summary: string;
};

export type AnalyticsExecution = {
  importedFile?: string;
  contextDescription?: string;
  sqlRowCount?: number;
  sqlRows?: Record<string, unknown>[];
  chartSummary?: string;
  graphTrace?: GraphNodeTrace[];
};

export type AnalyticsValidation = {
  approved: boolean;
  issues: string[];
  suggestedFixes: string[];
  shouldEscalateToClarification: boolean;
  clarificationQuestion: string;
};
