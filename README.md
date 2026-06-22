# simulador-copa-2026

Simulador Monte Carlo da Copa do Mundo FIFA 2026. Ele calcula fase de grupos, melhores terceiros, chaveamento oficial do mata-mata, probabilidades por fase e relatorios em CSV, JSON e TXT, com destaque para o Brasil.

O simulador roda offline a partir dos arquivos em `data/`, mas tambem tem uma camada V2 para atualizar resultados por scraping gratuito ou por providers externos quando houver API configurada.

## Instalacao

```bash
pip install -r requirements.txt
```

## Uso Rapido

Simular usando apenas os dados locais:

```bash
python main.py --simulations 50000 --seed 42 --offline --team Brazil
python main.py --simulations 50000 --seed 42 --offline --team Brasil
python main.py --simulations 50000 --seed 42 --offline --team "Estados Unidos"
```

Simular com rating calibrado e preset equilibrado:

```bash
python main.py --simulations 50000 --seed 42 --offline --rating-source calibrated --model-preset balanced --team Brasil
```

Atualizar resultados via scraping gratuito e sair:

```bash
python main.py --scrape-results-only
```

Atualizar resultados via scraping gratuito e simular em seguida:

```bash
python main.py --scrape-results --simulations 50000 --seed 42 --team Brazil
```

Fluxo diario recomendado:

```bash
python main.py --scrape-results-only
python main.py --simulations 50000 --seed 42 --offline --team Brazil
python main.py --recalibrate-ratings --offline --team Brazil
python main.py --simulations 50000 --seed 42 --offline --use-adjusted-ratings --team Brazil
python main.py --rating-source calibrated --model-preset balanced --team Brazil
python main.py --rating-source calibrated --weights-file output/best_model_weights.json --team Brazil
python main.py --compare-weight-files data/model_weights.json output/best_model_weights.json --team Brazil --simulations 50000 --seed 42
python main.py --analyze-weights --model-preset balanced
python main.py --compare-presets --team Brazil --simulations 50000 --seed 42
python main.py --sensitivity-analysis --team Brazil --simulations 50000 --seed 42
python main.py --backtest
python main.py --tune-weights
```

Testar um cenario sem alterar permanentemente `matches.json`:

```bash
python main.py --scenario data/scenario.example.json --team Brazil
```

Rodar testes:

```bash
pytest
```

`--seed` torna o resultado reproduzivel. Sem seed, cada execucao pode variar. O padrao e `--simulations 50000`.

O parametro `--team` aceita nomes canonicos em ingles e aliases comuns em pt-BR. Exemplos: `Brazil`, `Brasil`, `United States`, `EUA`, `Estados Unidos`, `Morocco`, `Marrocos`.

## Dashboard Web

O dashboard adiciona uma API local e um frontend React para visualizar relatorios em `output/` e executar comandos operacionais controlados.

Suba a API:

```bash
uvicorn backend.api:app --reload
```

Em outro terminal, suba o frontend:

```bash
cd frontend
npm install
npm run dev
```

Abra:

```text
http://localhost:5173
```

Endpoints principais:

- `GET /api/dashboard`: resumo dos relatorios locais.
- `GET /api/global`: panorama global.
- `GET /api/commands`: lista de acoes permitidas.
- `POST /api/commands/run`: executa uma acao permitida.
- `POST /api/jobs`: inicia uma acao em background.
- `GET /api/jobs`: lista jobs em memoria.
- `GET /api/jobs/{job_id}`: consulta status e saida de um job.

As operacoes do dashboard usam allowlist. O frontend nao envia shell livre; ele envia uma `action`, e a API monta comandos seguros como:

- `python main.py --source-health-check`
- `python main.py --dry-run-multisource`
- `python main.py --update-results-multisource-only`
- `python main.py --backtest`
- `python main.py --tune-weights`
- `python main.py --workflow full --team Brasil --global-report --simulations 50000 --seed 42`
- `python main.py --workflow full --all-teams --simulations 50000 --seed 42`

O ultimo comando executado pelo dashboard fica em:

```text
output/dashboard_commands/latest.json
```

O historico e o estado dos jobs do dashboard ficam em:

```text
output/dashboard_jobs/jobs.json
```

Esse arquivo e salvo em disco para que a tela de operacoes continue mostrando os workflows recentes depois de reiniciar a API ou trabalhar offline. Se a API cair enquanto um job estiver `queued` ou `running`, ele sera recarregado como `failed`, pois o processo de execucao anterior nao existe mais.

Jobs `failed` funcionam como uma DLQ local. Eles podem ser reenfileirados pelo dashboard ou pelo endpoint:

```text
POST /api/jobs/{job_id}/retry
```

O retry cria um novo job com a mesma `action`, `team`, `simulations` e `seed`, mantendo o job antigo no historico e registrando `retried_from` no job novo. Ele nao retoma do meio do comando anterior; workflows sao reexecutados de forma idempotente a partir dos arquivos locais.

Os botoes do frontend usam a fila de jobs por padrao. Status possiveis:

- `queued`: aguardando execucao.
- `running`: em execucao.
- `succeeded`: terminou com sucesso.
- `failed`: terminou com erro.

## Comandos

- `--offline`: usa apenas os JSONs locais.
- `--scrape-results-only`: raspa resultados/fixtures de fonte publica, atualiza `data/matches.json` se houver mudanca e encerra.
- `--scrape-results`: raspa resultados/fixtures antes de simular.
- `--update-data`: tenta atualizar dados via providers configurados antes de simular.
- `--update-data-only`: tenta atualizar dados via providers configurados e encerra.
- `--update-results`: atualiza apenas resultados via providers configurados e encerra.
- `--update-odds`: atualiza apenas odds via providers configurados e encerra.
- `--update-rankings`: atualiza apenas rankings via providers configurados e encerra.
- `--recalibrate-ratings`: gera `data/adjusted_ratings.json` com base nos resultados reais salvos.
- `--use-adjusted-ratings`: usa `data/adjusted_ratings.json` na simulacao.
- `--rating-source calibrated`: calcula e usa `data/calibrated_ratings.json`.
- `--model-preset`: usa preset de `data/model_presets.json`.
- `--weights-file`: usa um arquivo JSON de pesos customizados. Tem prioridade sobre `--model-preset`.
- `--compare-weight-files`: compara dois ou mais arquivos de pesos.
- `--analyze-weights`: mostra decomposicao dos ratings calibrados e gera `rating_breakdown`.
- `--compare-presets`: compara presets para um time.
- `--sensitivity-analysis`: roda variacoes de modelo para um time.
- `--backtest`: avalia jogos finalizados com Brier Score, Log Loss e acuracia.
- `--tune-weights`: testa grade pequena de pesos e salva a melhor config em `output/best_model_weights.json`.

## Ratings Ajustados pela Forma

Por padrao, o simulador usa `data/ratings.json` como forca base. Para refletir a forma real no torneio, rode:

```bash
python main.py --recalibrate-ratings --offline --team EUA
python main.py --simulations 50000 --seed 42 --offline --use-adjusted-ratings --team EUA
```

A recalibracao aplica bonus por vitoria/empate, saldo de gols e resultado contra adversario mais forte, com limite conservador de `+/-80` pontos por selecao. Isso evita que dois jogos transformem uma selecao intermediaria em favorita absoluta, mas permite que uma campanha forte aumente a chance futura.

## Ratings Calibrados V3

O rating calibrado combina:

- rating base;
- forma no torneio;
- ajuste por forca do adversario;
- bonus de sede para anfitrioes;
- odds/mercado quando houver dados normalizados;
- incerteza do modelo.

Arquivos principais:

- `data/model_weights.json`: pesos padrao.
- `data/model_presets.json`: presets como `balanced`, `conservative`, `recent_form`, `market_weighted`, `high_upset`, `favorite_heavy`.
- `data/calibrated_ratings.json`: rating final e decomposicao por selecao.

Exemplos:

```bash
python main.py --rating-source calibrated --model-preset balanced --team Brasil
python main.py --rating-source calibrated --model-preset high_upset --team Brasil
python main.py --rating-source calibrated --weights-file output/best_model_weights.json --team Brasil
python main.py --analyze-weights --model-preset balanced
```

Arquivos de pesos customizados podem ser um objeto de pesos direto, conter `{"weights": {...}}`, ou ser o JSON gerado por `--tune-weights` com `best.config`.

Para comparar pesos:

```bash
python main.py --compare-weight-files data/model_weights.json output/best_model_weights.json --team Brasil --simulations 50000 --seed 42
```

Gera:

- `output/weights_comparison_Brazil.csv`
- `output/weights_comparison_Brazil.txt`

Relatorios gerados:

- `output/rating_breakdown.csv`
- `output/rating_breakdown.json`
- `output/model_explanation.txt`

O CSV principal tambem inclui intervalo de confianca Monte Carlo para probabilidades-chave, como titulo, final e semifinal.

## Backtesting e Tuning

Para avaliar o modelo contra jogos ja finalizados:

```bash
python main.py --backtest
```

Gera:

- `output/backtest_report.txt`
- `output/backtest_results.csv`

Para testar combinacoes simples de pesos sem sobrescrever `data/model_weights.json`:

```bash
python main.py --tune-weights
```

Gera:

- `output/best_model_weights.json`

## Comparacao de Presets

```bash
python main.py --compare-presets --team Brasil --simulations 50000 --seed 42
python main.py --sensitivity-analysis --team Brasil --simulations 50000 --seed 42
```

Gera arquivos como:

- `output/preset_comparison_Brazil.csv`
- `output/preset_comparison_Brazil.txt`
- `output/sensitivity_Brazil.csv`
- `output/sensitivity_Brazil.txt`

## Scraping Gratuito

O scraper atual usa a pagina publica:

```text
https://en.wikipedia.org/wiki/2026_FIFA_World_Cup
```

Ela lista fixtures, placares e referencias para relatorios FIFA. O scraper:

- le os 72 jogos da fase de grupos;
- compara com `data/matches.json`;
- atualiza apenas jogos com mudanca real;
- registra `Sem mudanca` quando os dados ja estao iguais;
- nao cria duplicados;
- salva HTML bruto em `data/raw/` para auditoria local.

Exemplo de saida:

```text
[ok] wikipedia:scrape_results
  72 partidas lidas; 0 atualizadas; 72 sem mudanca; 0 ignoradas.
  Amostra:
  - Sem mudanca em A05: Mexico x South Africa.
```

## Dados

- `data/groups.json`: grupos.
- `data/matches.json`: jogos, placares e status.
- `data/ratings.json`: rating tipo Elo usado pelo modelo.
- `data/knockout_bracket.json`: chaveamento oficial informado.
- `data/third_place_mapping.json`: matriz completa com as 495 combinacoes dos terceiros.
- `data/external_sources.json`: configuracao de fontes externas.
- `data/odds.json`, `data/fifa_ranking.json`, `data/elo_ratings.json`: dados externos normalizados.
- `data/adjusted_ratings.json`: ratings recalibrados pela forma no torneio.
- `data/calibrated_ratings.json`: ratings calibrados V3 com decomposicao.
- `data/model_weights.json`: pesos do modelo.
- `data/model_presets.json`: presets de simulacao.
- `data/update_log.json`: log das tentativas de atualizacao.
- `data/snapshots/`: snapshots antes de atualizacoes.
- `data/raw/`: HTML bruto de scraping para auditoria local.
- `data/team_aliases.json`: mapa de aliases de selecoes em ingles e pt-BR.

Para atualizar manualmente um resultado em `data/matches.json`, use:

```json
{
  "status": "finished",
  "home_score": 1,
  "away_score": 0
}
```

Jogos ainda nao realizados devem ficar com `status: "scheduled"` e placares `null`.

## Saidas

A simulacao gera:

- `output/probabilities.csv`
- `output/probabilities.json`
- `output/summary.txt`

O relatorio mostra favoritos ao titulo, chances por fase, desempenho do Brasil e caminho mais comum no Round of 32.

## Modelo

Jogos de grupo ainda nao realizados usam um modelo Poisson simplificado baseado na diferenca de rating. Mata-mata usa probabilidade logistica por rating e nao permite empate.

Criterios de desempate simplificados: pontos, saldo de gols, gols pro e rating. A FIFA usa criterios adicionais; esta versao documenta essa simplificacao.

## Terceiros e Chaveamento

Classificam:

- 12 lideres de grupo;
- 12 vice-lideres;
- 8 melhores terceiros.

Os terceiros sao ordenados por pontos, saldo, gols pro e rating. Slots como `1C`, `2F`, `W73` e `3A/B/C/D/F` sao resolvidos em `src/knockout.py`.

O simulador valida que `third_place_mapping.json` tem exatamente 495 combinacoes e executa com `STRICT_THIRD_PLACE_MAPPING = True`. Se uma combinacao estiver ausente ou incorreta, a execucao falha.

## Limitacoes

- Ratings sao aproximados.
- Modelo Poisson e simplificado.
- Nao usa xG.
- Nao usa odds em tempo real por padrao.
- Nao modela lesoes/suspensoes.
- Criterios de desempate FIFA estao simplificados.
- Scraping depende da estrutura da pagina publica usada como fonte.

## Proximos Passos

- Adicionar criterios oficiais completos de desempate.
- Integrar ranking FIFA/Elo atualizado.
- Melhorar calibracao com odds quando houver fonte acessivel.
- Adicionar dashboard web.
- Adicionar historico comparativo antes/depois de cada rodada.

## Odds de mercado via Oddschecker

O projeto possui uma coleta leve de odds do mercado `Vencedor da Copa` no Oddschecker. A coleta alimenta um CSV local e, em seguida, normaliza as odds em `data/odds.json`, que é lido pelo modelo calibrado como uma âncora leve de mercado.

### Coletar odds uma vez

```powershell
python main.py --fetch-market-odds-only
```

Arquivos gerados/atualizados:

```text
data/market_odds_manual.csv
data/odds.json
output/market_odds_report.txt
```

### Coletar de tempos em tempos

```powershell
python main.py --fetch-market-odds-only --market-odds-runs 4 --market-odds-interval-minutes 30
```

Esse comando faz 4 coletas, com 30 minutos entre elas. Se o scraping falhar, o sistema usa o CSV local como cache, exceto se `--no-market-odds-cache` for informado.

### Usar CSV manual sem scraping

```powershell
python main.py --import-market-odds --market-odds-csv data/market_odds_manual.csv
```

### Comparar modelo vs mercado

Depois de rodar o workflow com relatório global:

```powershell
python main.py --market-comparison
```

Saídas:

```text
output/market_comparison.csv
output/market_comparison_report.txt
```

### Workflow completo com odds

```powershell
python main.py --workflow full --all-teams --simulations 300000 --seed 42 --with-market-odds
```

O workflow busca odds antes das simulações, alimenta `data/odds.json`, usa o componente de mercado no rating calibrado e gera comparação modelo vs mercado no final.

## Workflow unificado com odds de mercado

O painel de **Operações** possui o botão **Workflow com odds**. Ele executa em um único job:

1. coleta odds do Oddschecker;
2. preserva registros do CSV/cache manual quando o scraping retorna dados parciais;
3. normaliza `data/odds.json`;
4. roda o workflow global;
5. gera comparação `modelo x mercado`.

Comando equivalente:

```powershell
python main.py --workflow odds --all-teams --simulations 300000 --seed 42
```

Comandos individuais continuam disponíveis:

```powershell
python main.py --fetch-market-odds-only
python main.py --fetch-market-odds-only --market-odds-runs 4 --market-odds-interval-minutes 30
python main.py --import-market-odds --market-odds-csv data/market_odds_manual.csv
python main.py --market-comparison
python main.py --workflow full --all-teams --simulations 300000 --seed 42 --with-market-odds
```

O scraping é tratado como fonte opcional: se falhar ou vier parcial, o projeto usa o CSV/cache local como fallback e não quebra o workflow.

