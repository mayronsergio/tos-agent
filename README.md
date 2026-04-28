# Code Support Agent

Aplicacao web interna para consultar codigo Java legado, WAR descompilado e plugins proprios. O objetivo e ajudar analistas e desenvolvedores a localizar regras de negocio, fluxos, validacoes, tabelas envolvidas e causas provaveis de erros, sempre com evidencias de arquivo, classe e metodo.

## Stack

- Backend: Python, FastAPI
- Indexacao: SymbolIndex local, analisador Java estrutural e LlamaIndex
- Grafo: JSON local preparado para migracao futura para Neo4j
- Banco vetorial: Qdrant
- LLM: OpenAI API, Ollama local ou modo `mock`
- Frontend: React com Vite
- Execucao: Docker Compose

## Subir a aplicacao

```bash
cp .env.example .env
docker compose up --build
```

Abra:

- Frontend: http://localhost:5173
- Backend OpenAPI: http://localhost:8000/docs
- Qdrant: http://localhost:6333/dashboard

## Importar Codigo (.zip)

A importacao foi unificada em uma unica tela: **Importar codigo (.zip)**.

O ZIP precisa conter pelo menos um destes itens:

- arquivos `.java`;
- um repositorio Maven local contendo `*-sources.jar`;
- um repositorio Maven local contendo `.jar` com bytecode para decompilacao.

Apenas arquivos `.pom` nao sao suficientes. Se o ZIP nao tiver `.java`, `.jar` ou `.class`, a API retorna:

```text
Nenhum codigo fonte ou bytecode encontrado no ZIP
```

### ZIP com codigo fonte

Se o ZIP contiver codigo fonte direto, a aplicacao indexa arquivos relevantes:

- `.java`
- `.xml`
- `.properties`
- `.yml` / `.yaml`
- `.sql`
- `.jsp` / `.xhtml` / `.html`

Arquivos `.pom` nao contam como codigo valido e nao sao indexados como evidencia.

### ZIP com repositorio Maven local

Se o ZIP contiver estrutura como:

```text
athenas/tosp/{artifactId}/{version}/
```

Exemplo:

```text
athenas/tosp/aam/1.13.2/
  aam-1.13.2.jar
  aam-1.13.2-sources.jar
  aam-1.13.2.pom
```

A aplicacao detecta automaticamente os artifacts, identifica as versoes disponiveis e seleciona a versao mais recente de cada `artifactId` usando comparacao de versao Maven-like, nao ordenacao simples de string.

Para cada artifact/version:

1. Se existir `*-sources.jar`, extrai e indexa os `.java` e arquivos relevantes.
2. Se nao existir `sources.jar`, mas existir `.jar`, tenta decompilar com CFR.
3. Se nao existir `sources.jar` nem `.jar`, ignora o artifact e registra o motivo.

### Decompilacao

A decompilacao usa CFR. Configure:

```env
DECOMPILER=cfr
CFR_JAR_PATH=/tools/cfr.jar
```

A saida decompilada e salva em:

```text
data/imports/{importId}/decompiled/{artifactId}/
```

Se CFR nao estiver configurado e o artifact so tiver `.jar`, o artifact registra erro de decompilacao e nao gera falsa indexacao.

### Metadados

Cada importacao grava:

```text
data/imports/{importId}/
  raw/
  extracted/
  decompiled/
  index-metadata.json
  code-graph.json
```

O `index-metadata.json` registra:

- artifacts encontrados;
- artifacts processados;
- artifacts ignorados e motivo;
- quantidade de arquivos uteis indexados, sem contar `.pom`;
- tempo de processamento;
- erros de decompilacao;
- checksum do ZIP.

As evidencias indexadas preservam, quando aplicavel:

- `artifactId`
- `version`
- `sourceType` (`sources` ou `decompiled`)
- pacote
- classe
- metodo
- arquivo

## Arquitetura de Conhecimento Local

O Code Support Agent usa uma base local composta por tres camadas:

1. **SymbolIndex** em SQLite: armazena classes, interfaces, enums, annotations, pacote, metodos, atributos, constantes, tabela JPA, camada detectada, superclass, generic superclass, argumentos genericos, interfaces e metodos sobrescritos.
2. **Grafo de codigo** em `data/imports/{importId}/code-graph.json`: materializa relacoes como `CLASS_EXTENDS_CLASS`, `CLASS_IMPLEMENTS_INTERFACE`, `METHOD_CALLS_METHOD`, `CLASS_USES_CLASS`, `FIELD_HAS_TYPE`, `ENTITY_MAPS_TABLE`, `CONTROLLER_USES_SERVICE`, `SERVICE_USES_REPOSITORY`, `CLASS_HAS_GENERIC_ARGUMENT`, `METHOD_OVERRIDES_METHOD`, `CLASS_INHERITS_METHOD` e `CLASS_INHERITS_FIELD`.
3. **Chunks tecnicos para RAG**: cada simbolo indexado funciona como chunk tecnico com arquivo, pacote, classe, metodo, assinatura aproximada, annotations, camada, linhas e trecho original.

### Analisador Java

O analisador principal fica no subprojeto Maven `code-analysis-worker`. Ele usa JavaParser + JavaSymbolSolver para processar arquivos `.java`, resolver AST, tipos, heranca, generics, annotations, fields, metodos e chamadas reais quando possivel.

Build do worker:

```bash
cd code-analysis-worker
mvn -DskipTests package
```

O backend tenta executar automaticamente:

```text
java -jar code-analysis-worker/target/code-analysis-worker.jar
```

Tambem e possivel configurar explicitamente:

```env
JAVA_ANALYSIS_WORKER_COMMAND=java -jar /app/code-analysis-worker/target/code-analysis-worker.jar
JAVA_ANALYSIS_WORKER_TIMEOUT_SECONDS=120
```

Se o worker Java nao existir, falhar ou nao conseguir analisar a base, o backend usa fallback Python em `backend/app/indexing/extractors.py`. O contrato de saida e o mesmo, portanto SymbolIndex, grafo, API e UI continuam compativeis.

## Busca Tecnica

A busca diferencia:

- `symbol_query`: nome de classe, arquivo, metodo, entidade, tabela ou enum.
- `descriptive_query`: frase sobre erro, fluxo, regra, comportamento ou validacao.

Para `symbol_query`, a ordem e:

1. SymbolIndex;
2. grafo local;
3. chunks textuais;
4. busca semantica, quando configurada.

O ranking aplica pesos tecnicos para classe/interface/enum exata, arquivo exato, entidade JPA, tabela, metodo, campo/constante, pacote, mencao textual e semantica. A normalizacao ignora case, acentos, `.java`, barra inicial, camelCase, PascalCase, snake_case, kebab-case e plural simples.

Os resultados sao agrupados por arquivo para evitar que varios chunks do mesmo arquivo escondam arquivos mais relevantes.

## Chat Tecnico

Antes de buscar evidencias, o chat classifica a intencao:

- `ENTITY_ATTRIBUTES`
- `CLASS_STRUCTURE`
- `METHOD_FLOW`
- `VALIDATION_RULE`
- `ERROR_CAUSE`
- `DATABASE_MAPPING`
- `GENERIC`

Para `ENTITY_ATTRIBUTES`, o agente usa filtro forte: prioriza classe/arquivo exato, confirma entidade por `@Entity`, pacote `model/entity` ou layer `entity`, extrai atributos proprios, busca superclass e separa atributos herdados. Controllers, services, activities e validators nao entram como evidencia principal.

Para fluxo, erro e regra, o evidence pack combina SymbolIndex, grafo e chunks para incluir classe concreta, superclass, classe generica, tipo parametrizado, service/activity, repository/DAO e entidade/tabela quando houver. O pacote e limitado a poucos arquivos relevantes; o chat nao envia chunks aleatorios em massa.

Quando nao ha evidencia suficiente, a resposta deve declarar:

```text
Nao encontrei evidencia suficiente no codigo indexado para responder com seguranca.
```

## Endpoints

Status do indice:

```bash
curl http://localhost:8000/api/index/status
```

Grafo de uma classe:

```bash
curl http://localhost:8000/api/graph/class/Navio
```

Entidades detectadas:

```bash
curl http://localhost:8000/api/entities
```

Services, activities, controllers e repositories detectados:

```bash
curl http://localhost:8000/api/services
```

## Configuracoes

Voce pode alterar pela tela **Configuracoes** ou por `.env`:

```env
LLM_PROVIDER=mock
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
OLLAMA_MODEL=llama3.1
MAX_IMPORT_SIZE_MB=5000
MAX_IMPORT_FILE_SIZE_MB=512
DECOMPILER=cfr
CFR_JAR_PATH=
```

## API Principal

Importar ZIP:

```bash
curl -X POST http://localhost:8000/api/imports/zip \
  -F "file=@codebase.zip" \
  -F "reset=true"
```

Busca:

```bash
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"TB_CLIENTE\",\"mode\":\"hybrid\",\"limit\":10}"
```

Chat:

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"Por que o cadastro de cliente pode falhar?\",\"limit\":8}"
```

## Regras do Agente

- Toda resposta deve citar artifact, versao, arquivo, classe e metodo quando disponiveis.
- Perguntas de atributos devem separar atributos proprios e herdados.
- Heranca, generics e metodos sobrescritos/herdados devem ser considerados antes da resposta.
- Correcoes devem priorizar solucao via aplicacao.
- Sugestoes de banco de dados aparecem apenas como ultimo recurso e com alerta de risco.
- O agente nao deve inventar regra de negocio que nao esteja evidenciada no codigo.
- Quando a evidencia for insuficiente, a resposta deve declarar que a conclusao e hipotese.

## Evolucao Recomendada

- **JavaParser + JavaSymbolSolver**: o worker ja gera o mesmo JSON de simbolos/relacoes usado pelo backend. Evolucoes naturais sao adicionar classpath externo completo, resolver overloads complexos entre artifacts Maven e enriquecer chamadas por tipo de variavel.
- **Neo4j**: importar `code-graph.json` para labels `Class`, `Method`, `Field`, `Table`, `Artifact` e relacoes equivalentes aos tipos atuais.
- **Banco vetorial**: manter Qdrant/LlamaIndex para consultas descritivas, sempre com score menor que SymbolIndex e grafo em consultas de simbolo.
- **CLI**: os comandos equivalentes hoje sao endpoints:
  - `code-rag index --zip arquivo.zip` => `POST /api/imports/zip`
  - `code-rag ask "..."` => `POST /api/chat`
  - `code-rag graph --class Navio` => `GET /api/graph/class/Navio`
  - `code-rag entities` => `GET /api/entities`
  - `code-rag services` => `GET /api/services`

## Testes

```bash
cd backend
pip install -r requirements.txt
pytest
```

Frontend:

```bash
cd frontend
npm install
npm run build
```
