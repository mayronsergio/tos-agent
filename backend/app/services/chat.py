from __future__ import annotations

import re
import uuid
from collections import defaultdict
from enum import Enum

from app.llm.providers import LlmProvider
from app.models.schemas import ChatEvidence, ChatMessage, ChatResponse, Evidence, SearchMode
from app.services.heritage import AttributeInfo, ClassStructure, HeritageResolver
from app.services.search import SearchService


ANTI_HALLUCINATION_MESSAGE = "Não encontrei evidência suficiente no código indexado para afirmar isso com segurança."

QUERY_EXPANSIONS = {
    "mercadoria": ["merchandise", "commodity", "goods", "carga", "item"],
    "saida": ["saída", "exit", "outbound", "output", "SAIDA"],
    "saída": ["saida", "exit", "outbound", "output", "SAIDA"],
    "entrada": ["inbound", "input", "ENTRADA"],
    "pesagem": ["weighing", "weight", "balanca", "balança", "peso"],
    "nota": ["note", "invoice", "notaFiscal", "documento"],
    "movimentacao": ["movimentação", "movement", "move", "transaction"],
    "movimentação": ["movimentacao", "movement", "move", "transaction"],
    "cadastro": ["registration", "register", "config", "setup", "entity"],
    "concluir": ["finish", "finalize", "complete", "close", "finalizar"],
    "finalizar": ["finish", "finalize", "complete", "close", "concluir"],
}

VALIDATION_TERMS = ("valid", "validate", "valida", "throw new", "exception", "addError", "@not", "required", "obrig")
PERSISTENCE_TERMS = ("select ", " update ", " insert ", " delete ", " from ", " join ", "repository", "dao", "entitymanager")
CONSTANT_TERMS = ("enum", "static final", "status", "situacao", "situação", "constante")

_CONVERSATIONS: dict[str, list[ChatMessage]] = defaultdict(list)


class ChatIntent(str, Enum):
    ENTITY_ATTRIBUTES = "ENTITY_ATTRIBUTES"
    CLASS_STRUCTURE = "CLASS_STRUCTURE"
    METHOD_FLOW = "METHOD_FLOW"
    VALIDATION_RULE = "VALIDATION_RULE"
    ERROR_CAUSE = "ERROR_CAUSE"
    DATABASE_MAPPING = "DATABASE_MAPPING"
    GENERIC = "GENERIC"


def clear_conversations() -> None:
    _CONVERSATIONS.clear()


class ChatService:
    def __init__(self, search_service: SearchService, llm: LlmProvider):
        self.search_service = search_service
        self.llm = llm

    async def answer(
        self,
        message: str,
        top_k: int = 20,
        conversation_id: str | None = None,
        history: list[ChatMessage] | None = None,
        investigation_mode: bool = False,
    ) -> ChatResponse:
        conversation_id = conversation_id or str(uuid.uuid4())
        merged_history = [*(_CONVERSATIONS.get(conversation_id) or []), *(history or [])]
        search_text = self._search_text(message, merged_history)
        intent = self._detect_intent(search_text)
        terms = self._expand_terms(search_text)
        resolver = HeritageResolver(self.search_service.repository.all_snippets())
        if intent == ChatIntent.ENTITY_ATTRIBUTES:
            structure = resolver.find_entity_candidate(search_text)
            evidences = self._collect_entity_evidences(structure, terms, top_k) if structure else []
        else:
            evidences = self._collect_evidences(search_text, terms, top_k, intent, resolver)

        _CONVERSATIONS[conversation_id].append(ChatMessage(role="user", content=message))
        if len(_CONVERSATIONS[conversation_id]) > 12:
            _CONVERSATIONS[conversation_id] = _CONVERSATIONS[conversation_id][-12:]

        confidence = self._confidence(evidences, intent)
        if confidence == "low":
            answer = self._low_confidence_answer(message, evidences)
        elif intent == ChatIntent.ENTITY_ATTRIBUTES:
            answer = self._entity_attributes_answer(evidences, confidence)
        else:
            answer = self._grounded_answer(message, evidences, confidence, investigation_mode, intent)

        suggested = self._suggest_follow_up(evidences, confidence)
        _CONVERSATIONS[conversation_id].append(ChatMessage(role="assistant", content=answer[:3000]))
        return ChatResponse(answer=answer, confidence=confidence, intent=intent.value, evidences=evidences, suggestedFollowUp=suggested)

    def _search_text(self, message: str, history: list[ChatMessage]) -> str:
        recent = " ".join(item.content for item in history[-4:] if item.role == "user")
        return f"{recent} {message}".strip()

    def _detect_intent(self, text: str) -> ChatIntent:
        normalized = self._normalize(text)
        if any(term in normalized for term in ("atributo", "campo", "propriedade", "fields")) and any(term in normalized for term in ("entidade", "entity", "classe", "class")):
            return ChatIntent.ENTITY_ATTRIBUTES
        if any(term in normalized for term in ("tabela", "banco", "sql", "mapeamento", "mapping", "repository", "dao")):
            return ChatIntent.DATABASE_MAPPING
        if any(term in normalized for term in ("erro", "falha", "exception", "por que", "porque", "causa")):
            return ChatIntent.ERROR_CAUSE
        if any(term in normalized for term in ("validacao", "validar", "regra", "obrigatorio", "required")):
            return ChatIntent.VALIDATION_RULE
        if any(term in normalized for term in ("fluxo", "chama", "executa", "metodo", "salva", "processa")):
            return ChatIntent.METHOD_FLOW
        if any(term in normalized for term in ("qual classe", "classe faz", "controller", "service", "activity")):
            return ChatIntent.CLASS_STRUCTURE
        return ChatIntent.GENERIC

    def _expand_terms(self, text: str) -> list[str]:
        normalized = self._normalize(text)
        tokens = [token for token in re.findall(r"[\wÀ-ÿ]+", normalized) if len(token) >= 3]
        terms: list[str] = []
        for token in tokens:
            terms.append(token)
            terms.extend(QUERY_EXPANSIONS.get(token, []))
        status_matches = re.findall(r"\b[A-Z_]{3,}\b", text)
        terms.extend(status_matches)
        quoted = re.findall(r'"([^"]+)"', text)
        terms.extend(quoted)
        seen: set[str] = set()
        return [term for term in terms if not (term.lower() in seen or seen.add(term.lower()))][:60]

    def _collect_evidences(self, query: str, terms: list[str], top_k: int, intent: ChatIntent, resolver: HeritageResolver) -> list[ChatEvidence]:
        candidates: dict[tuple[str, int | None, str | None], ChatEvidence] = {}
        queries = [query, " ".join(terms[:16]), *terms[:24]]
        for item in queries:
            if not item.strip():
                continue
            limit = max(8, min(top_k, 30))
            for evidence in self.search_service.search(item, SearchMode.hybrid, limit):
                enriched = self._to_chat_evidence(evidence, terms)
                if not self._matches_intent(enriched, intent):
                    continue
                key = (enriched.file_path, enriched.line_start, enriched.method_name or enriched.class_name)
                if key not in candidates or enriched.score > candidates[key].score:
                    candidates[key] = enriched

        reranked = sorted(candidates.values(), key=lambda evidence: evidence.score, reverse=True)
        return resolver.limit_files(resolver.enrich_evidences(reranked), max_files=min(25, top_k))

    def _collect_entity_evidences(self, structure: ClassStructure, terms: list[str], top_k: int) -> list[ChatEvidence]:
        evidences: list[ChatEvidence] = []
        if structure.evidence:
            entity = self._to_chat_evidence(structure.evidence, terms, override_type="entidade")
            entity.superclass = structure.superclass
            entity.sourceFileOfSuperclass = structure.superclass_file
            evidences.append(entity)
        for field in structure.own_attributes:
            evidences.append(self._attribute_evidence(structure, field, inherited=False))
        for field in structure.inherited_attributes:
            evidences.append(self._attribute_evidence(structure, field, inherited=True))
        return evidences[:top_k]

    def _to_chat_evidence(self, evidence: Evidence, terms: list[str], override_type: str | None = None) -> ChatEvidence:
        evidence_type = override_type or self._classify(evidence)
        score = evidence.score + self._rerank_boost(evidence, evidence_type, terms)
        payload = evidence.model_dump()
        payload["score"] = round(score, 3)
        payload.pop("reason", None)
        payload.pop("evidenceType", None)
        return ChatEvidence(
            **payload,
            evidenceType=evidence_type,
            reason=self._reason(evidence, evidence_type, terms),
        )

    def _attribute_evidence(self, structure: ClassStructure, field: AttributeInfo, inherited: bool) -> ChatEvidence:
        return ChatEvidence(
            file_path=structure.source_file,
            filePath=structure.source_file,
            class_name=structure.class_name,
            superclass=structure.superclass,
            sourceFileOfSuperclass=structure.superclass_file,
            matchedSymbol=field.name,
            attributeType=field.type,
            attributeAnnotations=field.annotations,
            snippet=f"{field.type or ''} {field.name}".strip(),
            tags=["field", "inherited" if inherited else "own"],
            score=100 if not inherited else 90,
            finalScore=100 if not inherited else 90,
            symbolScore=100 if not inherited else 90,
            matchType="atributo herdado" if inherited else "atributo proprio",
            evidenceType="atributo herdado" if inherited else "atributo proprio",
            reason=f"Atributo {'herdado' if inherited else 'proprio'} declarado em {field.origin_class}.",
        )

    def _matches_intent(self, evidence: ChatEvidence, intent: ChatIntent) -> bool:
        if intent == ChatIntent.GENERIC:
            return True
        if intent == ChatIntent.METHOD_FLOW:
            return evidence.evidenceType in {"controller", "service", "persistÃªncia", "regra de negÃ³cio", "validaÃ§Ã£o"} or bool(evidence.superclass or evidence.genericSuperclass)
        if intent == ChatIntent.VALIDATION_RULE:
            return evidence.evidenceType in {"validaÃ§Ã£o", "service", "regra de negÃ³cio"}
        if intent == ChatIntent.ERROR_CAUSE:
            return evidence.evidenceType in {"validaÃ§Ã£o", "service", "controller", "persistÃªncia", "regra de negÃ³cio"} or bool(evidence.message)
        if intent == ChatIntent.DATABASE_MAPPING:
            return evidence.evidenceType in {"persistÃªncia", "consulta", "entidade"} or bool(evidence.table_name)
        if intent == ChatIntent.CLASS_STRUCTURE:
            return evidence.evidenceType in {"controller", "service", "entidade", "regra de negÃ³cio"} or bool(evidence.genericSuperclass or evidence.superclass)
        return True

    def _classify(self, evidence: Evidence) -> str:
        haystack = self._normalize(" ".join([evidence.snippet, evidence.validation or "", evidence.layer or "", " ".join(evidence.tags)]))
        if evidence.validation or any(term in haystack for term in VALIDATION_TERMS):
            return "validação"
        if evidence.layer == "controller/action":
            return "controller"
        if evidence.layer == "service" or "service" in self._normalize(evidence.class_name or ""):
            return "service"
        if evidence.layer == "dao/repository" or any(term in haystack for term in PERSISTENCE_TERMS):
            return "persistência"
        if evidence.entity_name or evidence.layer == "entity":
            return "entidade"
        if evidence.table_name:
            return "consulta"
        if evidence.language and evidence.language != "java":
            return "configuração"
        return "regra de negócio"

    def _rerank_boost(self, evidence: Evidence, evidence_type: str, terms: list[str]) -> float:
        haystack = self._normalize(
            " ".join(
                [
                    evidence.file_path,
                    evidence.class_name or "",
                    evidence.method_name or "",
                    evidence.table_name or "",
                    evidence.message or "",
                    evidence.validation or "",
                    evidence.snippet,
                ]
            )
        )
        boost = 0.0
        boost += sum(0.35 for term in terms if self._normalize(term) in haystack)
        if evidence.message and any(self._normalize(term) in self._normalize(evidence.message) for term in terms):
            boost += 3.0
        if evidence.table_name and any(self._normalize(term) in self._normalize(evidence.table_name) for term in terms):
            boost += 2.5
        if evidence.class_name and any(self._normalize(term) in self._normalize(evidence.class_name) for term in terms):
            boost += 2.0
        if evidence.method_name and any(self._normalize(term) in self._normalize(evidence.method_name) for term in terms):
            boost += 2.0
        if evidence_type == "validação":
            boost += 2.5
        if evidence_type in {"service", "regra de negócio"}:
            boost += 1.4
        if evidence_type == "controller":
            boost += 1.1
        if evidence_type in {"persistência", "consulta"}:
            boost += 1.0
        if any(term in haystack for term in CONSTANT_TERMS):
            boost += 1.0
        return boost

    def _reason(self, evidence: Evidence, evidence_type: str, terms: list[str]) -> str:
        matches = [
            term
            for term in terms
            if self._normalize(term)
            and self._normalize(term)
            in self._normalize(" ".join([evidence.class_name or "", evidence.method_name or "", evidence.message or "", evidence.table_name or "", evidence.snippet]))
        ][:4]
        parts = [f"Trecho classificado como {evidence_type}"]
        if matches:
            parts.append(f"contém termo(s) relacionado(s): {', '.join(matches)}")
        if evidence.layer:
            parts.append(f"camada detectada: {evidence.layer}")
        if evidence.message:
            parts.append("inclui mensagem de erro/validação")
        if evidence.table_name:
            parts.append(f"cita tabela {evidence.table_name}")
        return "; ".join(parts) + "."

    def _confidence(self, evidences: list[ChatEvidence], intent: ChatIntent = ChatIntent.GENERIC) -> str:
        if not evidences:
            return "low"
        if intent == ChatIntent.ENTITY_ATTRIBUTES:
            if any(item.evidenceType == "entidade" for item in evidences) and any(item.evidenceType in {"atributo proprio", "atributo herdado"} for item in evidences):
                return "high"
            return "low"
        max_score = max(evidence.score for evidence in evidences)
        strong_types = {evidence.evidenceType for evidence in evidences[:6]}
        if len(evidences) >= 4 and max_score >= 6 and ("validação" in strong_types or "service" in strong_types):
            return "high"
        if max_score >= 5 and ("validação" in strong_types or "service" in strong_types):
            return "medium"
        if len(evidences) >= 2 and max_score >= 2.5:
            return "medium"
        return "low"

    def _entity_attributes_answer(self, evidences: list[ChatEvidence], confidence: str) -> str:
        main = next((item for item in evidences if item.evidenceType == "entidade"), evidences[0])
        own = [item for item in evidences if item.evidenceType == "atributo proprio"]
        inherited = [item for item in evidences if item.evidenceType == "atributo herdado"]

        def fmt(item: ChatEvidence) -> str:
            annotations = f" ({', '.join(item.attributeAnnotations)})" if item.attributeAnnotations else ""
            return f"- {item.attributeType or 'tipo desconhecido'} {item.matchedSymbol}{annotations}"

        return (
            "Resumo:\n"
            f"A entidade principal encontrada foi {main.class_name or main.matchedSymbol}. A lista abaixo usa apenas atributos encontrados no indice.\n\n"
            "Estrutura da entidade:\n"
            "Atributos proprios:\n"
            + ("\n".join(fmt(item) for item in own) if own else "- Nenhum atributo proprio encontrado.")
            + "\n\nAtributos herdados:\n"
            + ("\n".join(fmt(item) for item in inherited) if inherited else "- Nenhum atributo herdado encontrado.")
            + "\n\nHeranca:\n"
            + f"- Classe pai: {main.superclass or 'nao identificada'}"
            + (f" ({main.sourceFileOfSuperclass})" if main.sourceFileOfSuperclass else "")
            + "\n\nObservacoes:\n"
            + "- Getters/setters e metodos foram ignorados na extracao de atributos.\n"
            + "- Campos herdados aparecem separados para evitar mistura com a classe concreta.\n\n"
            + "Grau de confianca:\n"
            + ("Alto." if confidence == "high" else "Baixo.")
            + "\n\nProxima pergunta:\n"
            + f"Quais metodos usam a entidade {main.class_name or main.matchedSymbol}?"
        )

    def _grounded_answer(self, question: str, evidences: list[ChatEvidence], confidence: str, investigation_mode: bool, intent: ChatIntent = ChatIntent.GENERIC) -> str:
        main = evidences[0]
        evidence_lines = [self._format_location(evidence) for evidence in evidences[:8]]
        flow = self._flow_summary(evidences, investigation_mode)
        cause = self._possible_cause(question, evidences)
        app_solution = self._app_solution(evidences)
        database = self._database_section(evidences)
        confidence_text = {"high": "Alto", "medium": "Médio", "low": "Baixo"}[confidence]
        confidence_reason = (
            "incluindo validações/serviços relacionados."
            if confidence == "high"
            else "com evidências relevantes, mas ainda incompletas para afirmar todo o fluxo."
        )
        return (
            "Resumo:\n"
            f"A evidência mais forte aponta para {main.class_name or main.file_path}"
            f"{'.' + main.method_name if main.method_name else ''}, em {main.artifact_id or 'artifact desconhecido'}:{main.version or 'versão desconhecida'}. "
            "A conclusão abaixo está limitada aos trechos recuperados do índice.\n\n"
            "Evidências encontradas:\n"
            + "\n".join(f"- {line}" for line in evidence_lines)
            + "\n\nAnálise técnica:\n"
            + flow
            + "\n\nPossível causa:\n"
            + cause
            + "\n\nSolução recomendada pela aplicação:\n"
            + app_solution
            + "\n\nBanco de dados:\n"
            + database
            + "\n\nGrau de confiança:\n"
            + f"{confidence_text}. O índice retornou {len(evidences)} evidência(s), com maior score {main.score:.2f}, "
            + confidence_reason
            + "\n\nPróxima pergunta útil:\n"
            + self._suggest_follow_up(evidences, confidence)
        )

    def _low_confidence_answer(self, question: str, evidences: list[ChatEvidence]) -> str:
        found = "\n".join(f"- {self._format_location(evidence)}" for evidence in evidences[:5]) or "- Nenhuma classe, método ou mensagem relevante foi recuperada."
        return (
            "Resumo:\n"
            f"{ANTI_HALLUCINATION_MESSAGE}\n\n"
            "Evidências encontradas:\n"
            f"{found}\n\n"
            "Análise técnica:\n"
            "Os trechos recuperados não permitem reconstruir o fluxo ou a regra de negócio com segurança.\n\n"
            "Possível causa:\n"
            "Ainda é hipótese. Faltam termos mais específicos, como nome da tela, classe, entidade, tabela, mensagem exata ou status interno.\n\n"
            "Solução recomendada pela aplicação:\n"
            "Informe a mensagem exata do erro, tela, ação executada e entidade afetada para localizar validações ou services relacionados.\n\n"
            "Banco de dados:\n"
            "Não há evidência suficiente de tabela, entidade ou query para sugerir análise de banco.\n\n"
            "Grau de confiança:\n"
            "Baixo. A resposta não encontrou evidências fortes no código indexado.\n\n"
            "Próxima pergunta útil:\n"
            "Qual é a mensagem exata exibida na tela ou o nome da entidade envolvida?"
        )

    def _flow_summary(self, evidences: list[ChatEvidence], investigation_mode: bool) -> str:
        by_type = defaultdict(list)
        for evidence in evidences[:10]:
            by_type[evidence.evidenceType].append(evidence)
        lines = []
        for evidence_type in ("controller", "service", "validação", "persistência", "consulta", "entidade", "configuração", "regra de negócio"):
            if evidence_type in by_type:
                names = ", ".join(self._symbol_name(item) for item in by_type[evidence_type][:3])
                lines.append(f"- {evidence_type}: {names}.")
        structural = []
        for evidence in evidences[:8]:
            details = []
            if evidence.superclass:
                details.append(f"superclasse {evidence.superclass}")
            if evidence.genericSuperclass:
                details.append(f"generico {evidence.genericSuperclass}")
            if evidence.genericArguments:
                details.append(f"tipos {', '.join(evidence.genericArguments)}")
            if evidence.inheritedMethods:
                details.append(f"metodos herdados {', '.join(evidence.inheritedMethods[:4])}")
            if evidence.overriddenMethods:
                details.append(f"metodos sobrescritos {', '.join(evidence.overriddenMethods[:4])}")
            if details:
                structural.append(f"- {self._symbol_name(evidence)}: {'; '.join(details)}.")
        if structural:
            lines.append("- Estrutura/heranca/generics considerados:")
            lines.extend(structural[:6])
        if investigation_mode:
            tables = sorted({item.table_name for item in evidences if item.table_name})
            messages = sorted({item.message for item in evidences if item.message})
            if tables:
                lines.append(f"- Tabelas citadas no fluxo: {', '.join(tables[:8])}.")
            if messages:
                lines.append(f"- Mensagens recuperadas: {'; '.join(messages[:3])}.")
            lines.append("- Pontos de falha a verificar: validações de status, permissões/parâmetros e gravação por DAO/repository quando existirem nas evidências.")
        return "\n".join(lines) if lines else "Os trechos recuperados indicam relação com a pergunta, mas não formam um fluxo completo."

    def _possible_cause(self, question: str, evidences: list[ChatEvidence]) -> str:
        validations = [item for item in evidences if item.evidenceType == "validação" or item.message]
        if validations:
            location = self._format_location(validations[0])
            return f"O problema pode estar sendo bloqueado por validação encontrada em {location}. Verifique se o estado/cadastro informado atende às condições desse método."
        services = [item for item in evidences if item.evidenceType == "service"]
        if services:
            return f"O fluxo provavelmente passa por {self._format_location(services[0])}; a causa pode estar em regra de negócio ou pré-condição desse service."
        return "A causa ainda é hipótese; as evidências mostram relação textual, mas não uma validação conclusiva."

    def _app_solution(self, evidences: list[ChatEvidence]) -> str:
        if any(item.evidenceType == "validação" for item in evidences):
            return "Priorize corrigir o cadastro, status, parâmetro, permissão ou etapa do fluxo que alimenta a validação citada. Refaça a operação pela tela após ajustar esses dados."
        if any(item.evidenceType in {"controller", "service"} for item in evidences):
            return "Reproduza o fluxo pela tela vinculada ao controller/service encontrado e confira parâmetros obrigatórios, permissões e sequência de etapas antes de tentar intervenção técnica."
        return "Use a aplicação para confirmar dados obrigatórios e contexto da operação antes de qualquer correção fora do fluxo normal."

    def _database_section(self, evidences: list[ChatEvidence]) -> str:
        db_evidences = [item for item in evidences if item.table_name or item.evidenceType in {"persistência", "consulta"}]
        if not db_evidences:
            return "Não há evidência clara de tabela, entidade ou query relacionada nos trechos selecionados."
        tables = sorted({item.table_name for item in db_evidences if item.table_name})
        table_text = f" Tabelas citadas: {', '.join(tables)}." if tables else ""
        return (
            "Há evidência de persistência/consulta relacionada."
            + table_text
            + " Use o banco apenas para leitura e diagnóstico; UPDATE/DELETE direto deve ser último recurso por risco de burlar regras da aplicação, auditoria e integridade."
        )

    def _suggest_follow_up(self, evidences: list[ChatEvidence], confidence: str) -> str:
        if confidence == "low":
            return "Qual é a mensagem exata exibida na tela ou o nome da entidade envolvida?"
        first = evidences[0]
        if first.method_name:
            return f"Explique o fluxo completo que chama o método {first.method_name}."
        if first.class_name:
            return f"Quais métodos da classe {first.class_name} participam desse fluxo?"
        return "Quais validações e tabelas aparecem nos arquivos relacionados?"

    def _format_location(self, evidence: ChatEvidence) -> str:
        symbol = self._symbol_name(evidence)
        artifact = f"{evidence.artifact_id or 'artifact desconhecido'}:{evidence.version or 'versão desconhecida'}"
        line = f":{evidence.line_start}" if evidence.line_start else ""
        return f"{artifact} - {evidence.file_path}{line} - {symbol} - {evidence.reason}"

    def _symbol_name(self, evidence: Evidence) -> str:
        return ".".join(part for part in [evidence.class_name, evidence.method_name] if part) or evidence.class_name or evidence.file_path

    def _normalize(self, text: str) -> str:
        return text.lower().replace("ã", "a").replace("á", "a").replace("à", "a").replace("â", "a").replace("é", "e").replace("ê", "e").replace("í", "i").replace("ó", "o").replace("ô", "o").replace("õ", "o").replace("ú", "u").replace("ç", "c")
