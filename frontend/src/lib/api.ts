import { recordFrontendLog } from "./frontendLogs";

export type Evidence = {
  file_path: string;
  filePath?: string | null;
  fileName?: string | null;
  artifact_id?: string | null;
  version?: string | null;
  source_type?: string | null;
  language?: string | null;
  package?: string | null;
  class_name?: string | null;
  superclass?: string | null;
  genericSuperclass?: string | null;
  genericArguments?: string[];
  interfaces?: string[];
  overriddenMethods?: string[];
  inheritedMethods?: string[];
  sourceFileOfSuperclass?: string | null;
  genericClass?: string | null;
  relatedEntity?: string | null;
  relatedServiceActivity?: string | null;
  relationFromGraph?: string | null;
  attributeType?: string | null;
  attributeAnnotations?: string[];
  method_name?: string | null;
  entity_name?: string | null;
  layer?: string | null;
  table_name?: string | null;
  message?: string | null;
  validation?: string | null;
  line_start?: number | null;
  line_end?: number | null;
  snippet: string;
  tags: string[];
  score: number;
  finalScore?: number;
  semanticScore?: number;
  textScore?: number;
  symbolScore?: number;
  matchType?: string;
  matchedSymbol?: string | null;
  symbolType?: string | null;
  reason?: string;
  evidenceType?: string;
};

export type SearchMode = "text" | "semantic" | "hybrid";
export type LlmProvider = "mock" | "openai" | "ollama";

export type RuntimeConfig = {
  allowed_import_roots: string;
  max_import_size_mb: number;
  max_import_file_size_mb: number;
  decompiler: string;
  cfr_jar_path?: string | null;
  llm_provider: LlmProvider;
  openai_api_key?: string | null;
  openai_api_key_set?: boolean;
  openai_model: string;
  ollama_base_url: string;
  ollama_model: string;
  qdrant_url: string;
  qdrant_collection: string;
  enable_vector_index: boolean;
};

function normalizeApiBase(baseUrl: string): string {
  const withoutTrailingSlash = baseUrl.replace(/\/+$/, "");
  return withoutTrailingSlash.endsWith("/api") ? withoutTrailingSlash : `${withoutTrailingSlash}/api`;
}

const API_BASE = normalizeApiBase(
  import.meta.env.VITE_API_BASE ||
    `${window.location.protocol}//${window.location.hostname || "localhost"}:8000/api`,
);

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const isFormData = options?.body instanceof FormData;
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { ...(isFormData ? {} : { "Content-Type": "application/json" }), ...(options?.headers ?? {}) },
      ...options,
    });
  } catch (error) {
    recordFrontendLog("error", "api", `Falha de conexao com ${path}: ${(error as Error).message}`);
    throw new Error(`Falha de conexão com a API em ${API_BASE}. Verifique se o backend está rodando e acessível pelo navegador.`);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    recordFrontendLog("error", "api", `HTTP ${response.status} em ${path}: ${body.detail ?? "erro desconhecido"}`);
    throw new Error(body.detail ?? `Erro HTTP ${response.status}`);
  }
  return response.json();
}

export function getStatus() {
  return request<{ indexed_files: number; indexed_symbols: number; metadata: Record<string, unknown> }>("/index/status");
}

export function getConfig() {
  return request<RuntimeConfig>("/config");
}

export function updateConfig(config: RuntimeConfig) {
  return request<RuntimeConfig>("/config", {
    method: "PUT",
    body: JSON.stringify(config),
  });
}

export type ZipImportResult = {
  importId: string;
  originalFilename: string;
  metadataPath: string;
  processedArtifacts: number;
  skippedArtifacts: number;
  decompiled: boolean;
  importedFiles: number;
  indexedSymbols: number;
  skippedFiles: number;
  extractedFiles: number;
  errors: string[];
  message: string;
};

export type ImportJob = {
  jobId: string;
  importId: string;
  status: "queued" | "running" | "completed" | "failed";
  phase: string;
  progress: number;
  current?: number;
  total?: number;
  message: string;
  result?: ZipImportResult | null;
  error?: string | null;
  startedAt?: string;
  finishedAt?: string | null;
};

export type BackendLogEntry = {
  timestamp: string;
  level: string;
  logger: string;
  message: string;
};

export function importZip(file: File, reset: boolean) {
  const form = new FormData();
  form.append("file", file);
  form.append("reset", String(reset));
  return request<ImportJob>("/imports/zip", {
    method: "POST",
    body: form,
  });
}

export function getImportStatus(jobId: string) {
  return request<ImportJob>(`/imports/${jobId}`);
}

export function getBackendLogs(limit = 200) {
  return request<{ source: string; entries: BackendLogEntry[] }>(`/logs?limit=${limit}&source=backend`);
}

export function resetApp() {
  return request<{ status: string; message: string }>("/reset", {
    method: "POST",
  });
}

export function searchCode(query: string, mode: SearchMode, limit = 20) {
  return request<{ query: string; mode: SearchMode; evidences: Evidence[] }>("/search", {
    method: "POST",
    body: JSON.stringify({ query, mode, limit }),
  });
}

export function chat(message: string, topK = 20, investigationMode = false, conversationId?: string) {
  return request<{
    answer: string;
    confidence: "high" | "medium" | "low";
    intent: string;
    evidences: Evidence[];
    suggestedFollowUp: string;
    assumptions: string[];
    risk_alerts: string[];
  }>("/chat", {
    method: "POST",
    body: JSON.stringify({ message, topK, investigationMode, conversationId }),
  });
}
