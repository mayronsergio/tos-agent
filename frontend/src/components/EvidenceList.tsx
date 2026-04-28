import { Braces, FileCode2, Layers3, MapPin } from "lucide-react";
import React from "react";
import type { Evidence } from "../lib/api";

type Props = {
  evidences: Evidence[];
};

export function EvidenceList({ evidences }: Props) {
  const grouped = evidences.reduce<Array<{ filePath: string; items: Evidence[] }>>((acc, evidence) => {
    const filePath = evidence.filePath || evidence.file_path;
    const existing = acc.find((group) => group.filePath === filePath);
    if (existing) {
      existing.items.push(evidence);
    } else {
      acc.push({ filePath, items: [evidence] });
    }
    return acc;
  }, []);

  if (!evidences.length) {
    return (
      <section className="empty-state">
        <FileCode2 size={34} />
        <h3>Nenhuma evidencia para exibir</h3>
        <p>Execute uma busca ou faca uma pergunta para visualizar os trechos de codigo usados pelo agente.</p>
      </section>
    );
  }

  return (
    <section className="evidence-section">
      <div className="section-heading">
        <div>
          <h3>Evidencias encontradas</h3>
          <p>{evidences.length} trecho(s) recuperado(s) do indice.</p>
        </div>
      </div>
      <div className="evidence-list">
        {grouped.map((group, groupIndex) => {
          const primary = group.items[0];
          const symbol = [primary.class_name, primary.method_name].filter(Boolean).join(".");
          const score = primary.finalScore ?? primary.score;
          return (
            <details className="evidence" key={group.filePath} open={groupIndex < 3}>
              <summary>
                <div className="evidence-title">
                  <FileCode2 size={18} />
                  <div>
                    <strong>{group.filePath}</strong>
                    <span>
                      {primary.matchType || "textual"} · linhas {primary.line_start ?? "?"}-{primary.line_end ?? "?"}
                      {group.items.length > 1 ? ` · ${group.items.length} trechos` : ""}
                    </span>
                  </div>
                </div>
                <small title="Pontuacao tecnica final">{score.toFixed(2)}</small>
              </summary>
              <div className="meta">
                {symbol && (
                  <span>
                    <Braces size={13} />
                    {symbol}
                  </span>
                )}
                {primary.matchedSymbol && <span>{primary.matchedSymbol}</span>}
                {primary.symbolScore !== undefined && <span>simbolo: {primary.symbolScore.toFixed(0)}</span>}
                {primary.textScore !== undefined && <span>texto: {primary.textScore.toFixed(0)}</span>}
                {primary.semanticScore !== undefined && <span>semantico: {primary.semanticScore.toFixed(0)}</span>}
                {primary.artifact_id && (
                  <span>
                    {primary.artifact_id}:{primary.version ?? "?"}
                  </span>
                )}
                {primary.source_type && <span>{primary.source_type}</span>}
                {primary.language && <span>{primary.language}</span>}
                {primary.table_name && <span>tabela: {primary.table_name}</span>}
                {primary.message && <span>mensagem</span>}
                {primary.validation && <span>validacao</span>}
                {primary.evidenceType && <span>{primary.evidenceType}</span>}
                {primary.package && (
                  <span>
                    <MapPin size={13} />
                    {primary.package}
                  </span>
                )}
                {primary.layer && (
                  <span>
                    <Layers3 size={13} />
                    {primary.layer}
                  </span>
                )}
                {primary.tags.map((tag) => (
                  <span key={tag}>{tag}</span>
                ))}
              </div>
              {primary.reason && <p className="evidence-reason">{primary.reason}</p>}
              <pre>{primary.snippet}</pre>
              {group.items.slice(1).map((evidence, index) => (
                <details className="evidence-nested" key={`${evidence.file_path}-${evidence.line_start}-${index}`}>
                  <summary>
                    {evidence.matchType || "textual"} · linhas {evidence.line_start ?? "?"}-{evidence.line_end ?? "?"} ·{" "}
                    {(evidence.finalScore ?? evidence.score).toFixed(2)}
                  </summary>
                  {evidence.reason && <p className="evidence-reason">{evidence.reason}</p>}
                  <pre>{evidence.snippet}</pre>
                </details>
              ))}
            </details>
          );
        })}
      </div>
    </section>
  );
}
