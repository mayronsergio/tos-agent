# Validacao real da ultima importacao TOS

Data da validacao: 2026-04-28  
Importacao validada: `20260428192444-35a4ef51`  
Arquivo de metadata: `backend/data/imports/20260428192444-35a4ef51/index-metadata.json`

## Resumo da importacao

| Item | Valor |
| --- | ---: |
| Arquivos uteis indexados | 6298 |
| Simbolos indexados | 84056 |
| Chunks indexados | 84056 |
| Entidades detectadas | 2340 |
| Services detectados | 1945 |
| Controllers detectados | 800 |
| Relacoes persistidas no grafo | 251943 |
| Tempo de processamento | 396.287s |

O endpoint `GET /api/index/status` respondeu com sucesso e confirmou os totais acima.

## Metricas do JavaParser

| Metrica | Valor | Validacao |
| --- | ---: | --- |
| `javaParserFiles` | 5253 | OK: maior que zero |
| `fallbackPythonFiles` | 0 | OK |
| `workerFailures` | 1 | Atencao: ha falha listada abaixo |
| `relationsGenerated` | 351173 | OK: maior que zero |
| `resolvedMethodCalls` | 63268 | OK: maior que zero |
| `unresolvedMethodCalls` | 113264 | Atencao: volume alto de chamadas nao resolvidas |

Falha encontrada:

- Artefato `common:1.13.2`: `CFR nao configurado. Informe CFR_JAR_PATH para decompilar bytecode.`

Artefato ignorado:

- `plugin:1.13.2`: `sem sources.jar ou jar`

## Evidencias estruturais confirmadas no indice

### Entidade Navio

Evidencia principal correta no SymbolIndex:

- artifactId: `nucleus`
- version: `1.13.2`
- arquivo: `work/nucleus-1.13.2/tosp/product/alm/nucleus/generic/transportes/navio/model/Navio.java`
- classe: `Navio`
- layer: `entity`
- annotations: `SuppressWarnings`, `Entity`, `Table`
- superclass: `Transporte`
- linhas aproximadas: `11-110`

Atributos proprios detectados em `Navio.java`:

- `chamada`: `java.lang.String`, annotations `Size`, `NotNull`
- `vpAnoConstrucao`: `java.lang.Integer`
- `vpArqueacaoBruta`: `java.lang.Double`
- `vpArqueacaoLiquida`: `java.lang.Double`
- `vpComprimento`: `java.lang.Double`
- `vpLargura`: `java.lang.Double`
- `vpPorte`: `java.lang.Double`
- `objetivoAtracacao`: `Navio.KDObjetivoAtracacao`

Atributos herdados detectados em `Transporte.java`:

- `id`: `java.lang.Long`, annotations `Id`, `Column`, `GeneratedValue`
- `nome`: `java.lang.String`, annotations `Size`, `NotNull`
- `identificador`: `java.lang.String`, annotations `NotNull`, `Size`
- `classeCarga`: `Configuracao.KDClasseCarga`
- `modal`: `Configuracao.KDModal`, annotation `NotNull`
- `paisId`: `java.lang.Long`
- `dispositivoId`: `java.lang.Long`
- `numero`: `java.lang.String`, annotation `Size`
- `spec`: `java.lang.String`, annotation `Size`
- `tara`: `java.lang.Double`
- `classe`: `Transporte.KDClasse`, annotation `NotNull`
- `ultimaTara`: `java.util.Date`
- `emExecucao`: `java.util.Date`

Relacoes relevantes confirmadas:

- `CLASS_EXTENDS_CLASS`: `Navio -> Transporte`
- `ANNOTATED_WITH`: `Navio -> Entity`
- `ANNOTATED_WITH`: `Navio -> Table`
- `CLASS_HAS_GENERIC_ARGUMENT`: `NavioSpecification -> Navio`
- `FIELD_HAS_TYPE`: campos de `Navio` resolvidos para `String`, `Integer`, `Double` e `Navio.KDObjetivoAtracacao`
- Usos de `Navio` encontrados em classes como `ExValidarNotaEmapTaskActivity`, `EstabilizarCS_TABELA_ITaskActivity` e `EstabilizarCS_TABELA_IITaskActivity`

### VinculoNotaNavio

Evidencias estruturais corretas no SymbolIndex:

- `VinculoNotaNavioServiceActivity`
  - artifactId: `celulose`
  - version: `1.13.2`
  - arquivo: `work/celulose-1.13.2/tosp/plugin/celulose/kernel/vinculonotanavio/activity/VinculoNotaNavioServiceActivity.java`
  - layer: `service`
  - superclass: `CoMaintainServiceActivity`
  - genericSuperclass: `CoMaintainServiceActivity<ManutenirVinculoNotaNavioTaskActivity>`

- `ManutenirVinculoNotaNavioController`
  - arquivo: `work/celulose-1.13.2/tosp/plugin/celulose/kernel/vinculonotanavio/controller/ManutenirVinculoNotaNavioController.java`
  - layer: `controller/action`
  - superclass: `CoMaintainController`
  - genericSuperclass: `CoMaintainController<VinculoNotaNavioServiceActivity>`

- `ManutenirVinculoNotaNavioTaskActivity`
  - arquivo: `work/celulose-1.13.2/tosp/plugin/celulose/kernel/vinculonotanavio/activity/ManutenirVinculoNotaNavioTaskActivity.java`
  - layer: `activity`
  - genericSuperclass: `CoMaintainTaskActivity<VinculoNotaNavio, VinculoNotaNavioDTO, VinculoNotaNavioSpecification, CoResource, VinculoNotaNavioResourceDTO>`

Relacoes relevantes confirmadas:

- `CLASS_HAS_GENERIC_ARGUMENT`: `ManutenirVinculoNotaNavioController -> VinculoNotaNavioServiceActivity`
- `CLASS_HAS_GENERIC_ARGUMENT`: `VinculoNotaNavioServiceActivity -> ManutenirVinculoNotaNavioTaskActivity`
- `CLASS_HAS_GENERIC_ARGUMENT`: `ManutenirVinculoNotaNavioTaskActivity -> VinculoNotaNavio`
- `CLASS_HAS_GENERIC_ARGUMENT`: `ManutenirVinculoNotaNavioTaskActivity -> VinculoNotaNavioSpecification`
- `CLASS_EXTENDS_CLASS`: `VinculoNotaNavio -> CoEntity`
- `ANNOTATED_WITH`: `VinculoNotaNavio -> Entity`
- `ANNOTATED_WITH`: `VinculoNotaNavio -> Table`

## Perguntas testadas no chat

As perguntas abaixo foram enviadas para `POST /api/chat` com `topK=12` e `investigationMode=true`.

| Pergunta | Intent retornada | Confianca | Resultado resumido | Validacao |
| --- | --- | --- | --- | --- |
| Quais sao os atributos da entidade Navio? | `ENTITY_ATTRIBUTES` | `high` | Respondeu sobre `ManutenirMedidaTaskActivity` e atributo `aIndicadorSpecification`. | Falhou. Evidencia principal incorreta. Nao usou `Navio.java`. Confianca incoerente. |
| Quais atributos Navio herda? | `GENERIC` | `high` | Priorizou `VinculoNotaNavio`, `ResumoOperacaoDTO`, `BilhetePesagem` e outros trechos. | Falhou. Deveria detectar pergunta de atributos/heranca e usar `Navio -> Transporte`. |
| Mostre o grafo da classe Navio. | `GENERIC` | `high` | Priorizou `Indicador`, `ArquivoTipo`, `Recurso` e outras classes por termo "classe". | Falhou. O endpoint dedicado `/api/graph/class/Navio` funciona, mas o chat nao o usa corretamente. |
| Quais classes usam Navio? | `GENERIC` | `high` | Priorizou `IndicadorController.classes` e `MercadoriaController.classes`. | Falhou. O ranking favoreceu a palavra "classes" em vez do simbolo `Navio`. |
| Qual service manipula VinculoNotaNavio? | `CLASS_STRUCTURE` | `high` | Evidencia principal foi a entidade `VinculoNotaNavio`; services genericos irrelevantes tambem apareceram. | Parcial. Encontrou o dominio certo, mas nao promoveu `VinculoNotaNavioServiceActivity` como resposta principal. |
| Onde e validado o vinculo entre nota e navio? | `GENERIC` | `high` | Priorizou `NotaFiscal`, `ExNotaFiscalSpecification` e DTOs de billing antes de evidencias de `VinculoNotaNavio`. | Falhou/parcial. Ha evidencias de `VinculoNotaNavio`, mas o ranking ainda mistura classes por termos genericos. |

## Endpoint de grafo

`GET /api/graph/class/Navio` respondeu com sucesso e retornou:

- `className`: `Navio`
- `superclass`: `Transporte`
- `genericArguments`: `[]`
- campos de `Navio`
- relacoes como `CLASS_EXTENDS_CLASS`, `ANNOTATED_WITH`, `FIELD_HAS_TYPE`, `CLASS_HAS_GENERIC_ARGUMENT`

Problema observado: a resposta tambem inclui arquivos e metodos de classes relacionadas que mencionam ou usam `Navio`, como `VinculoNotaNavio`, `OperacaoNavio`, `ReatracacaoNavio` e specifications. Isso e util para exploracao, mas para uma pergunta "grafo da classe Navio" o chat precisa distinguir:

- estrutura propria da classe;
- heranca direta;
- usos externos;
- classes com nome contendo `Navio`, mas que nao sao a classe `Navio`.

## Problemas encontrados

1. O SymbolIndex e o grafo contem evidencias corretas, mas o chat nao as prioriza corretamente.
2. Perguntas de atributos/heranca nao acionam de forma confiavel o pipeline estrutural `ENTITY_ATTRIBUTES`.
3. A confianca `high` esta sendo retornada mesmo com evidencia principal errada.
4. O ranking do chat ainda favorece termos genericos da pergunta, como `classe`, `classes`, `service`, `nota`, em vez do simbolo alvo.
5. O retorno serializado de evidencias do chat contem campos estruturais, mas a API tambem expõe chaves duplicadas ou inconsistentes (`file_path` e `filePath`, `artifact_id` e nao `artifactId`), o que facilita erros no frontend/validadores.
6. `table_name` de `Navio` veio `null` apesar de a classe ter `@Table`; o worker detectou a annotation, mas nao extraiu o valor da tabela para o campo normalizado.
7. Ha uma falha de worker/decompilacao no artefato `common:1.13.2` por CFR nao configurado.
8. O volume de `unresolvedMethodCalls` ainda e alto: 113264.

## Ajustes recomendados

1. Corrigir o pipeline de `ENTITY_ATTRIBUTES` para usar match exato no SymbolIndex antes de qualquer chunk textual.
2. Reclassificar perguntas como "Quais atributos Navio herda?" para uma intent estrutural, nao `GENERIC`.
3. Para perguntas de grafo, rotear explicitamente para o `CodeGraphService.class_relations(className)` ou equivalente antes de montar o evidence pack.
4. Aplicar filtro forte por simbolo alvo: se o alvo extraido for `Navio`, evidencias sem `class_name=Navio`, `target=Navio`, `source=Navio` ou relacao direta devem ter score baixo ou ser removidas.
5. Ajustar confianca: `high` somente quando a evidencia principal for match exato de classe/arquivo/tabela/metodo ou relacao direta no grafo.
6. Promover relacoes genericas na pergunta de service: `VinculoNotaNavio -> ManutenirVinculoNotaNavioTaskActivity -> VinculoNotaNavioServiceActivity -> ManutenirVinculoNotaNavioController`.
7. Extrair valores de `@Table` para `table_name`, incluindo `name` e `schema` quando existirem.
8. Normalizar o schema JSON de evidencias para expor apenas os nomes publicos esperados pelo frontend: `artifactId`, `filePath`, `className`, `methodName`.
9. Configurar `CFR_JAR_PATH` no ambiente de importacao ou documentar que artefatos sem `sources.jar` serao parcialmente ignorados.
10. Investigar os maiores grupos de `unresolvedMethodCalls` para melhorar classpath, type solver e imports multi-artifact.

## Conclusao

Validacao nao aprovada para o chat tecnico.

O worker JavaParser esta gerando um indice estrutural util e o grafo contem relacoes importantes de heranca, generics e tipos. A falha principal esta na etapa de selecao/ranking de evidencias do chat: as respostas ainda sao guiadas por matches textuais genericos e retornam alta confianca mesmo quando ignoram a evidencia estrutural correta.
