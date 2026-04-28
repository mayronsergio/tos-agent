import React, { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Code2,
  Database,
  FileArchive,
  FileSearch,
  KeyRound,
  MessageSquare,
  RefreshCw,
  Save,
  Search,
  Settings,
  ShieldAlert,
} from "lucide-react";
import {
  chat,
  Evidence,
  getBackendLogs,
  getConfig,
  getImportStatus,
  getStatus,
  ImportJob,
  importZip,
  RuntimeConfig,
  searchCode,
  SearchMode,
  resetApp,
  type BackendLogEntry,
  updateConfig,
} from "./lib/api";
import { EvidenceList } from "./components/EvidenceList";
import { getFrontendLogs, recordFrontendLog, subscribeFrontendLogs, type FrontendLogEntry } from "./lib/frontendLogs";
import "./styles.css";

type Tab = "import" | "search" | "chat" | "config" | "logs";
type LogSource = "backend" | "frontend";
type NoticeKind = "success" | "error" | "info";

const tabContent = {
  import: {
    eyebrow: "Importacao",
    title: "Importar codigo (.zip)",
    description: "Envie um ZIP com codigo fonte ou repositorio Maven local. O sistema detecta artifacts, escolhe a versao mais recente e indexa codigo real.",
  },
  search: {
    eyebrow: "Busca tecnica",
    title: "Pesquisar evidencias no codigo",
    description: "Encontre classes, metodos, tabelas, mensagens e validacoes com busca textual ou hibrida.",
  },
  chat: {
    eyebrow: "Assistente",
    title: "Conversar com o agente",
    description: "Faca perguntas sobre regras, fluxos, validacoes e causas provaveis de erro.",
  },
  config: {
    eyebrow: "Administracao",
    title: "Configurar variaveis da aplicacao",
    description: "Altere provedor de LLM, modelos, chave de API e parametros de importacao.",
  },
  logs: {
    eyebrow: "Observabilidade",
    title: "Logs da aplicacao",
    description: "Veja eventos recentes do backend e do frontend para diagnosticar importacoes, buscas, chamadas e falhas.",
  },
};

const defaultConfig: RuntimeConfig = {
  allowed_import_roots: "/data/imports",
  max_import_size_mb: 5000,
  max_import_file_size_mb: 512,
  decompiler: "cfr",
  cfr_jar_path: "",
  llm_provider: "mock",
  openai_api_key: "",
  openai_model: "gpt-4.1-mini",
  ollama_base_url: "http://ollama:11434",
  ollama_model: "llama3.1",
  qdrant_url: "http://qdrant:6333",
  qdrant_collection: "code_support_agent",
  enable_vector_index: true,
};

export default function App() {
  const [tab, setTab] = useState<Tab>("import");
  const [status, setStatus] = useState({ indexed_files: 0, indexed_symbols: 0 });
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [zipResult, setZipResult] = useState<NonNullable<ImportJob["result"]> | null>(null);
  const [importJob, setImportJob] = useState<ImportJob | null>(null);
  const [reset, setReset] = useState(true);
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [confidence, setConfidence] = useState<"high" | "medium" | "low" | "">("");
  const [detectedIntent, setDetectedIntent] = useState("");
  const [suggestedFollowUp, setSuggestedFollowUp] = useState("");
  const [investigationMode, setInvestigationMode] = useState(false);
  const [conversationId] = useState(() =>
    typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `conversation-${Date.now()}`
  );
  const [assumptions, setAssumptions] = useState<string[]>([]);
  const [riskAlerts, setRiskAlerts] = useState<string[]>([]);
  const [evidences, setEvidences] = useState<Evidence[]>([]);
  const [logSource, setLogSource] = useState<LogSource>("backend");
  const [backendLogs, setBackendLogs] = useState<BackendLogEntry[]>([]);
  const [frontendLogs, setFrontendLogs] = useState<FrontendLogEntry[]>(getFrontendLogs());
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [noticeKind, setNoticeKind] = useState<NoticeKind>("info");
  const [config, setConfig] = useState<RuntimeConfig>(defaultConfig);

  const current = tabContent[tab];
  const layerSummary = useMemo(() => {
    const layers = evidences.reduce<Record<string, number>>((acc, evidence) => {
      const key = evidence.layer || "nao identificada";
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {});
    return Object.entries(layers).slice(0, 4);
  }, [evidences]);

  function showNotice(message: string, kind: NoticeKind = "info") {
    setNotice(message);
    setNoticeKind(kind);
  }

  async function refreshStatus() {
    const data = await getStatus();
    setStatus({ indexed_files: data.indexed_files, indexed_symbols: data.indexed_symbols });
  }

  useEffect(() => {
    refreshStatus().catch((error) => showNotice(error.message, "error"));
    getConfig().then(setConfig).catch((error) => showNotice(error.message, "error"));
  }, []);

  useEffect(() => {
    const unsubscribe = subscribeFrontendLogs(() => {
      setFrontendLogs(getFrontendLogs());
    });

    const onError = (event: ErrorEvent) => {
      recordFrontendLog("error", "runtime", event.message || "Erro nao tratado no frontend");
    };
    const onUnhandledRejection = (event: PromiseRejectionEvent) => {
      recordFrontendLog("error", "runtime", event.reason instanceof Error ? event.reason.message : String(event.reason));
    };

    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onUnhandledRejection);
    return () => {
      unsubscribe();
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onUnhandledRejection);
    };
  }, []);

  useEffect(() => {
    if (!importJob || !["queued", "running"].includes(importJob.status)) {
      return;
    }
    const timer = window.setInterval(async () => {
      try {
        const job = await getImportStatus(importJob.jobId);
        setImportJob(job);
        if (job.status === "completed" && job.result) {
          setZipResult(job.result);
          setBusy(false);
          showNotice(`${job.result.message} ${job.result.importedFiles} arquivos uteis e ${job.result.indexedSymbols} simbolos indexados.`, "success");
          await refreshStatus();
        }
        if (job.status === "failed") {
          setBusy(false);
          showNotice(job.error || job.message || "Falha ao importar ZIP.", "error");
        }
      } catch (error) {
        setBusy(false);
        showNotice(error instanceof Error ? error.message : "Falha ao consultar progresso da importacao.", "error");
      }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [importJob?.jobId, importJob?.status]);

  useEffect(() => {
    if (tab !== "logs" || logSource !== "backend") {
      return;
    }
    let active = true;
    async function loadLogs() {
      try {
        const response = await getBackendLogs(200);
        if (active) {
          setBackendLogs(response.entries);
        }
      } catch (error) {
        if (active) {
          recordFrontendLog("error", "logs", error instanceof Error ? error.message : "Falha ao carregar logs do backend");
        }
      }
    }
    loadLogs();
    const timer = window.setInterval(loadLogs, 3000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [tab, logSource]);

  async function handleZipImport(event: FormEvent) {
    event.preventDefault();
    if (!zipFile) {
      showNotice("Selecione um arquivo .zip.", "error");
      return;
    }
    setBusy(true);
    setNotice("");
    recordFrontendLog("info", "import", `Importacao iniciada para ${zipFile.name} (reset=${reset})`);
    try {
      setZipResult(null);
      const job = await importZip(zipFile, reset);
      setImportJob(job);
      showNotice("Importacao iniciada. O processamento continua em segundo plano.", "info");
      recordFrontendLog("info", "import", `Job ${job.jobId} colocado em fila.`);
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "Falha ao importar ZIP.", "error");
      recordFrontendLog("error", "import", error instanceof Error ? error.message : "Falha ao importar ZIP.");
      setBusy(false);
    }
  }

  async function handleSearch(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setNotice("");
    recordFrontendLog("info", "search", `Busca executada: ${query} (${mode})`);
    try {
      const result = await searchCode(query, mode);
      setEvidences(result.evidences);
      showNotice(`${result.evidences.length} evidencia(s) encontrada(s).`, "success");
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "Falha na busca.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function handleChat(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setNotice("");
    recordFrontendLog("info", "chat", `Pergunta enviada ao agente: ${question}`);
    try {
      const result = await chat(question, 20, investigationMode, conversationId);
      setAnswer(result.answer);
      setConfidence(result.confidence);
      setDetectedIntent(result.intent);
      setSuggestedFollowUp(result.suggestedFollowUp);
      setAssumptions(result.assumptions);
      setRiskAlerts(result.risk_alerts);
      setEvidences(result.evidences);
      showNotice(`${result.evidences.length} evidencia(s) usadas na resposta.`, "success");
      recordFrontendLog("info", "chat", `Resposta recebida com confiança ${result.confidence} e ${result.evidences.length} evidencias.`);
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "Falha no chat.", "error");
      recordFrontendLog("error", "chat", error instanceof Error ? error.message : "Falha no chat.");
    } finally {
      setBusy(false);
    }
  }

  async function handleConfig(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setNotice("");
    recordFrontendLog("info", "config", "Salvar configuracoes solicitada.");
    try {
      const result = await updateConfig(config);
      setConfig(result);
      showNotice("Configuracoes salvas.", "success");
      recordFrontendLog("info", "config", "Configuracoes salvas.");
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "Falha ao salvar configuracoes.", "error");
      recordFrontendLog("error", "config", error instanceof Error ? error.message : "Falha ao salvar configuracoes.");
    } finally {
      setBusy(false);
    }
  }

  async function handleReset() {
    const confirmed = window.confirm("Isso vai apagar todos os dados indexados, importacoes, configuracoes salvas e historico local. Continuar?");
    if (!confirmed) {
      return;
    }
    setBusy(true);
    setNotice("");
    recordFrontendLog("warn", "reset", "Solicitacao de reset iniciada.");
    try {
      const result = await resetApp();
      setZipFile(null);
      setZipResult(null);
      setImportJob(null);
      setQuestion("");
      setAnswer("");
      setConfidence("");
      setDetectedIntent("");
      setSuggestedFollowUp("");
      setAssumptions([]);
      setRiskAlerts([]);
      setEvidences([]);
      await refreshStatus();
      getConfig().then(setConfig).catch((error) => showNotice(error.message, "error"));
      showNotice(result.message, "success");
      recordFrontendLog("info", "reset", result.message);
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "Falha ao resetar a aplicacao.", "error");
      recordFrontendLog("error", "reset", error instanceof Error ? error.message : "Falha ao resetar a aplicacao.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Bot size={24} />
          </div>
          <div>
            <h1>Code Support Agent</h1>
            <p>Analise assistida de codigo Java legado</p>
          </div>
        </div>

        <nav className="nav-list" aria-label="Navegacao principal">
          <button className={tab === "import" ? "active" : ""} onClick={() => setTab("import")} type="button">
            <FileArchive size={18} />
            <span>Importar ZIP</span>
          </button>
          <button className={tab === "search" ? "active" : ""} onClick={() => setTab("search")} type="button">
            <Search size={18} />
            <span>Pesquisar</span>
          </button>
          <button className={tab === "chat" ? "active" : ""} onClick={() => setTab("chat")} type="button">
            <MessageSquare size={18} />
            <span>Chat tecnico</span>
          </button>
          <button className={tab === "config" ? "active" : ""} onClick={() => setTab("config")} type="button">
            <Settings size={18} />
            <span>Configuracoes</span>
          </button>
          <button className={tab === "logs" ? "active" : ""} onClick={() => setTab("logs")} type="button">
            <FileSearch size={18} />
            <span>Logs</span>
          </button>
        </nav>

        <div className="index-card">
          <div className="index-card-header">
            <Database size={18} />
            <span>Indice atual</span>
          </div>
          <div className="index-metrics">
            <div>
              <strong>{status.indexed_files}</strong>
              <span>arquivos</span>
            </div>
            <div>
              <strong>{status.indexed_symbols}</strong>
              <span>evidencias</span>
            </div>
          </div>
          <button className="ghost-button" onClick={() => refreshStatus().catch((error) => showNotice(error.message, "error"))} type="button">
            <RefreshCw size={16} />
            Atualizar
          </button>
        </div>
      </aside>

      <section className="workspace">
        <header className="page-header">
          <div>
            <span className="eyebrow">{current.eyebrow}</span>
            <h2>{current.title}</h2>
            <p>{current.description}</p>
          </div>
          <div className="header-badge">
            <ShieldAlert size={16} />
            Respostas exigem evidencia
          </div>
        </header>

        <div className="toolbar-row">
          <button className="ghost-button danger" onClick={handleReset} type="button" disabled={busy}>
            <RefreshCw size={16} />
            Resetar tudo
          </button>
        </div>

        {notice && (
          <div className={`notice ${noticeKind}`} role="status">
            {noticeKind === "success" && <CheckCircle2 size={18} />}
            {noticeKind === "error" && <AlertTriangle size={18} />}
            {noticeKind === "info" && <FileSearch size={18} />}
            <span>{notice}</span>
          </div>
        )}

        {tab === "import" && (
          <section className="content-grid">
            <div className="main-column">
              <form className="surface form-surface" onSubmit={handleZipImport}>
                <div className="section-title">
                  <FileArchive size={20} />
                  <div>
                    <h3>Arquivo ZIP</h3>
                    <p>O ZIP pode conter codigo fonte direto ou um repositorio Maven local como athenas/tosp.</p>
                  </div>
                </div>
                <label>
                  Selecionar ZIP
                  <input accept=".zip,application/zip" type="file" onChange={(event) => setZipFile(event.target.files?.[0] ?? null)} />
                </label>
                <label className="toggle-row">
                  <input type="checkbox" checked={reset} onChange={(event) => setReset(event.target.checked)} />
                  <span>
                    <strong>Recriar indice antes de importar</strong>
                    <small>Use quando o ZIP representa a nova base completa de codigo.</small>
                  </span>
                </label>
                <div className="form-actions">
                  <button disabled={busy || !zipFile} type="submit">
                    <FileArchive size={18} />
                    {busy ? "Importando..." : "Enviar e indexar ZIP"}
                  </button>
                </div>
              </form>

              {importJob && ["queued", "running"].includes(importJob.status) && (
                <section className="surface">
                  <div className="section-title">
                    <RefreshCw size={20} />
                    <div>
                      <h3>Importacao em andamento</h3>
                      <p>{importJob.message}</p>
                    </div>
                  </div>
                  <div className="progress-block">
                    <div className="progress-header">
                      <span>{importJob.phase}</span>
                      <strong>{importJob.progress}%</strong>
                    </div>
                    <div className="progress-track">
                      <span style={{ width: `${Math.max(4, Math.min(100, importJob.progress))}%` }} />
                    </div>
                    {Boolean(importJob.total) && (
                      <small>
                        {importJob.current ?? 0} de {importJob.total} itens processados
                      </small>
                    )}
                  </div>
                </section>
              )}

              {zipResult && (
                <section className="surface">
                  <div className="section-title">
                    <CheckCircle2 size={20} />
                    <div>
                      <h3>Importacao concluida</h3>
                      <p>Metadados gravados em {zipResult.metadataPath}</p>
                    </div>
                  </div>
                  <div className="index-metrics light">
                    <div>
                      <strong>{zipResult.processedArtifacts}</strong>
                      <span>artifacts processados</span>
                    </div>
                    <div>
                      <strong>{zipResult.skippedArtifacts}</strong>
                      <span>artifacts ignorados</span>
                    </div>
                    <div>
                      <strong>{zipResult.importedFiles}</strong>
                      <span>arquivos uteis</span>
                    </div>
                    <div>
                      <strong>{zipResult.decompiled ? "sim" : "nao"}</strong>
                      <span>decompilacao</span>
                    </div>
                  </div>
                  {zipResult.errors.length > 0 && (
                    <div className="warning">
                      <AlertTriangle size={18} />
                      <span>{zipResult.errors.length} erro(s) ou aviso(s) registrados no metadata.</span>
                    </div>
                  )}
                </section>
              )}
            </div>

            <aside className="insights-panel">
              <h3>Regras</h3>
              <ul className="rule-list">
                <li>
                  <CheckCircle2 size={16} />
                  sources.jar tem prioridade sobre jar binario.
                </li>
                <li>
                  <FileArchive size={16} />
                  JAR sem sources exige CFR configurado.
                </li>
                <li>
                  <ShieldAlert size={16} />
                  Apenas .pom nao e codigo valido.
                </li>
                <li>
                  <Code2 size={16} />
                  Evidencias recebem artifactId, versao e sourceType.
                </li>
              </ul>
            </aside>
          </section>
        )}

        {tab === "search" && (
          <section className="content-grid">
            <div className="main-column">
              <form className="surface search-surface" onSubmit={handleSearch}>
                <div className="section-title">
                  <Search size={20} />
                  <div>
                    <h3>Consulta</h3>
                    <p>Pesquise por simbolo, tabela, texto de erro ou regra de validacao.</p>
                  </div>
                </div>
                <div className="query-row">
                  <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Ex.: validarCadastro, TB_CLIENTE, Cliente obrigatorio" />
                  <select value={mode} onChange={(event) => setMode(event.target.value as SearchMode)}>
                    <option value="hybrid">Hibrida</option>
                    <option value="text">Textual</option>
                    <option value="semantic">Semantica</option>
                  </select>
                  <button disabled={busy || !query.trim()} type="submit">
                    <Search size={18} />
                    Buscar
                  </button>
                </div>
              </form>
              <EvidenceList evidences={evidences} />
            </div>
            <aside className="insights-panel">
              <h3>Resumo</h3>
              <Metric label="Evidencias na tela" value={evidences.length} />
              <Metric label="Modo de busca" value={mode} />
              <div className="mini-list">
                <strong>Camadas encontradas</strong>
                {layerSummary.length ? (
                  layerSummary.map(([layer, count]) => (
                    <span key={layer}>
                      {layer} <b>{count}</b>
                    </span>
                  ))
                ) : (
                  <small>Aguardando resultados.</small>
                )}
              </div>
            </aside>
          </section>
        )}

        {tab === "chat" && (
          <section className="content-grid">
            <div className="main-column">
              <form className="surface form-surface" onSubmit={handleChat}>
                <div className="section-title">
                  <MessageSquare size={20} />
                  <div>
                    <h3>Pergunta tecnica</h3>
                    <p>O agente respondera usando apenas evidencias encontradas no indice.</p>
                  </div>
                </div>
                <textarea
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder="Ex.: Por que o cadastro de cliente pode falhar com documento invalido?"
                />
                <label className="toggle-row">
                  <input type="checkbox" checked={investigationMode} onChange={(event) => setInvestigationMode(event.target.checked)} />
                  <span>
                    <strong>Modo investigacao tecnica</strong>
                    <small>Inclui fluxo provavel, classes envolvidas, validacoes, pontos de falha e caminhos de correcao pela aplicacao.</small>
                  </span>
                </label>
                <div className="form-actions">
                  <button disabled={busy || !question.trim()} type="submit">
                    <MessageSquare size={18} />
                    {busy ? "Analisando..." : "Perguntar"}
                  </button>
                </div>
              </form>

              {answer && (
                <section className="surface answer">
                  <div className="answer-header">
                    <div className="section-title">
                      <Bot size={20} />
                      <div>
                        <h3>Resposta</h3>
                        <p>Conclusao gerada a partir das evidencias recuperadas.</p>
                      </div>
                    </div>
                    {detectedIntent && <span className="intent-badge">{detectedIntent}</span>}
                    {confidence && <span className={`confidence-badge ${confidence}`}>confiança {confidence}</span>}
                  </div>
                  <p>{answer}</p>
                  {confidence === "low" && (
                    <div className="warning">
                      <AlertTriangle size={18} />
                      <span>Pouca evidencia recuperada. A resposta deve ser tratada como hipotese ate localizar classes, metodos ou mensagens mais especificas.</span>
                    </div>
                  )}
                  {suggestedFollowUp && (
                    <div className="empty-inline">
                      <strong>Proxima pergunta util:</strong> {suggestedFollowUp}
                    </div>
                  )}
                  {assumptions.map((item) => (
                    <div className="warning" key={item}>
                      <AlertTriangle size={18} />
                      <span>{item}</span>
                    </div>
                  ))}
                  {riskAlerts.map((item) => (
                    <div className="risk" key={item}>
                      <ShieldAlert size={18} />
                      <span>{item}</span>
                    </div>
                  ))}
                </section>
              )}
              <EvidenceList evidences={evidences} />
            </div>
            <aside className="insights-panel">
              <h3>Criterios</h3>
              <ul className="rule-list">
                <li>
                  <CheckCircle2 size={16} />
                  Citar artifact, versao, arquivo, classe e metodo.
                </li>
                <li>
                  <CheckCircle2 size={16} />
                  Priorizar correcao pela aplicacao.
                </li>
                <li>
                  <AlertTriangle size={16} />
                  Banco de dados apenas como ultimo recurso.
                </li>
              </ul>
            </aside>
          </section>
        )}

        {tab === "config" && (
          <section className="content-grid">
            <form className="surface form-surface" onSubmit={handleConfig}>
              <div className="section-title">
                <Settings size={20} />
                <div>
                  <h3>Variaveis em tempo de execucao</h3>
                  <p>Configuracoes salvas no banco local substituem os valores do ambiente.</p>
                </div>
              </div>

              <div className="field-grid">
                <label>
                  Provedor de LLM
                  <select value={config.llm_provider} onChange={(event) => setConfig({ ...config, llm_provider: event.target.value as RuntimeConfig["llm_provider"] })}>
                    <option value="mock">Mock local</option>
                    <option value="openai">OpenAI API</option>
                    <option value="ollama">Ollama local</option>
                  </select>
                </label>
                <label>
                  Modelo OpenAI
                  <input value={config.openai_model} onChange={(event) => setConfig({ ...config, openai_model: event.target.value })} placeholder="gpt-4.1-mini" />
                </label>
              </div>

              <label>
                Chave OpenAI API
                <div className="secret-input">
                  <KeyRound size={18} />
                  <input
                    value={config.openai_api_key ?? ""}
                    onChange={(event) => setConfig({ ...config, openai_api_key: event.target.value })}
                    placeholder={config.openai_api_key_set ? "Chave configurada" : "sk-..."}
                    type="password"
                  />
                </div>
              </label>

              <div className="field-grid">
                <label>
                  URL Ollama
                  <input value={config.ollama_base_url} onChange={(event) => setConfig({ ...config, ollama_base_url: event.target.value })} placeholder="http://ollama:11434" />
                </label>
                <label>
                  Modelo Ollama
                  <input value={config.ollama_model} onChange={(event) => setConfig({ ...config, ollama_model: event.target.value })} placeholder="llama3.1" />
                </label>
              </div>

              <div className="field-grid">
                <label>
                  Limite total ZIP (MB)
                  <input type="number" min="1" value={config.max_import_size_mb} onChange={(event) => setConfig({ ...config, max_import_size_mb: Number(event.target.value) })} />
                </label>
                <label>
                  Limite por arquivo (MB)
                  <input type="number" min="1" value={config.max_import_file_size_mb} onChange={(event) => setConfig({ ...config, max_import_file_size_mb: Number(event.target.value) })} />
                </label>
              </div>

              <div className="field-grid">
                <label>
                  Decompiler
                  <select value={config.decompiler} onChange={(event) => setConfig({ ...config, decompiler: event.target.value })}>
                    <option value="cfr">CFR</option>
                  </select>
                </label>
                <label>
                  Caminho do CFR jar
                  <input value={config.cfr_jar_path ?? ""} onChange={(event) => setConfig({ ...config, cfr_jar_path: event.target.value })} placeholder="/tools/cfr.jar" />
                </label>
              </div>

              <div className="field-grid">
                <label>
                  URL Qdrant
                  <input value={config.qdrant_url} onChange={(event) => setConfig({ ...config, qdrant_url: event.target.value })} placeholder="http://qdrant:6333" />
                </label>
                <label>
                  Collection Qdrant
                  <input value={config.qdrant_collection} onChange={(event) => setConfig({ ...config, qdrant_collection: event.target.value })} placeholder="code_support_agent" />
                </label>
              </div>

              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={config.enable_vector_index}
                  onChange={(event) => setConfig({ ...config, enable_vector_index: event.target.checked })}
                />
                <span>
                  <strong>Ativar indice vetorial</strong>
                  <small>Ao mudar Qdrant ou collection, reimporte o ZIP para reconstruir vetores.</small>
                </span>
              </label>

              <div className="form-actions">
                <button disabled={busy} type="submit">
                  <Save size={18} />
                  {busy ? "Salvando..." : "Salvar configuracoes"}
                </button>
              </div>
            </form>
          </section>
        )}

        {tab === "logs" && (
          <section className="content-grid">
            <div className="main-column">
              <section className="surface form-surface">
                <div className="section-title">
                  <FileSearch size={20} />
                  <div>
                    <h3>Fontes de log</h3>
                    <p>Escolha entre logs do backend e eventos capturados no frontend.</p>
                  </div>
                </div>
                <div className="query-row logs-filter">
                  <select value={logSource} onChange={(event) => setLogSource(event.target.value as LogSource)}>
                    <option value="backend">Backend</option>
                    <option value="frontend">Frontend</option>
                  </select>
                  <button
                    type="button"
                    onClick={() => {
                      if (logSource === "backend") {
                        getBackendLogs(200)
                          .then((result) => setBackendLogs(result.entries))
                          .catch((error) => showNotice(error.message, "error"));
                      } else {
                        setFrontendLogs(getFrontendLogs());
                      }
                    }}
                  >
                    <RefreshCw size={18} />
                    Atualizar
                  </button>
                </div>
              </section>

              <section className="surface">
                <div className="section-title">
                  <Database size={20} />
                  <div>
                    <h3>Eventos recentes</h3>
                    <p>{logSource === "backend" ? `${backendLogs.length} entradas do servidor` : `${frontendLogs.length} entradas locais`}</p>
                  </div>
                </div>
                <div className="log-list">
                  {(logSource === "backend" ? backendLogs : frontendLogs).length ? (
                    (logSource === "backend" ? backendLogs : frontendLogs).map((entry, index) => (
                      <article className={`log-entry ${entry.level}`} key={`${entry.timestamp}-${index}`}>
                        <div className="log-entry-head">
                          <strong>{entry.level.toUpperCase()}</strong>
                          <span>{entry.timestamp}</span>
                        </div>
                        <div className="log-entry-body">
                          <small>{entry.logger ?? (entry as FrontendLogEntry).scope}</small>
                          <p>{entry.message}</p>
                        </div>
                      </article>
                    ))
                  ) : (
                    <div className="empty-inline">Nenhum log disponivel para esta origem.</div>
                  )}
                </div>
              </section>
            </div>
            <aside className="insights-panel">
              <h3>Observacao</h3>
              <ul className="rule-list">
                <li>
                  <CheckCircle2 size={16} />
                  Backend inclui requests, reset, importacao e eventos do processador.
                </li>
                <li>
                  <CheckCircle2 size={16} />
                  Frontend inclui acoes da tela, falhas de API e erros nao tratados.
                </li>
                <li>
                  <AlertTriangle size={16} />
                  Logs sao mantidos em memoria no processo atual do app.
                </li>
              </ul>
            </aside>
          </section>
        )}
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
