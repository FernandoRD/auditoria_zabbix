# Portabilidade: matplotlib para gráficos + Typst para PDF (remoção do Playwright)

## Contexto e motivação

O app depende do Playwright/Chromium em dois pontos: renderização dos gráficos Mermaid (`xychart-beta`) em PNG para exportação, e impressão do relatório HTML em PDF. O `playwright install --with-deps` só sabe instalar as bibliotecas de sistema do Chromium via `apt`/`dnf`, o que quebra a instalação em distros não-Debian (o usuário não conseguiu instalar no CachyOS/Arch) e torna o app pouco portável. Objetivo: eliminar o Playwright por completo, deixando toda a cadeia de exportação instalável só com `pip install -r requirements.txt`, funcionando igual em qualquer distro Linux e no Windows.

Decisões tomadas com o usuário:

- **Gráficos**: matplotlib (backend Agg, wheels universais, zero dependência de sistema).
- **PDF**: Typst via pacote pip `typst` (compilador Rust distribuído como wheel nativo para Linux/Windows/Mac). WeasyPrint foi descartado por exigir DLLs GTK/Pango no Windows; xhtml2pdf foi descartado por qualidade visual inferior num entregável de cliente.

## Insight central: o contrato com a IA não muda

O prompt (`prompts/report_template.txt`) já força a IA a emitir uma sintaxe `xychart-beta` rígida e pequena (title, x-axis, y-axis, line/bar). Em vez de trocar o formato por JSON, um parser Python (~60 linhas) lê essa mesma sintaxe e alimenta o matplotlib. Consequências:

- O prompt fica praticamente intocado (única mudança: REGRA DE OURO 4 troca "fluxogramas" por "tabelas", e ganha instrução de não usar outros tipos de diagrama Mermaid — sem browser não há como renderizá-los).
- Relatórios antigos e o fluxo "Regerar (Apenas IA)" com cache continuam exportando normalmente.
- As correções de alucinação já existentes (`lineChart|barChart` → `xychart-beta`, `data: [` → `line [`, etc., hoje em `_render_mermaid_charts`) são reaproveitadas como etapa de normalização antes do parse.

## Escopo

Inclui: novo módulo de renderização de gráficos, novo pipeline de PDF, prévia da janela de estilos, remoção do Playwright de requirements/Dockerfile, ajuste do prompt, atualização de README/TECHNICAL_REFERENCE/CLAUDE.md, testes unitários do parser/renderer.

Não inclui: renderização de flowcharts/outros diagramas Mermaid (ficam como bloco de código no export — fallback que já existe hoje); mudanças nos caminhos DOCX/ODT/MD além da fonte dos PNGs; mudanças no fluxo de IA.

## Arquitetura

### 1. `core/chart_renderer.py` (novo módulo)

- `normalize_mermaid(code: str) -> str` — aplica as correções de alucinação hoje embutidas em `_render_mermaid_charts` (regexes movidas para cá).
- `parse_xychart(code: str) -> dict | None` — parser puro da sintaxe `xychart-beta`. Retorna `{"title": str, "x_labels": [str], "y_label": str, "y_range": (min, max) | None, "series": [{"type": "line"|"bar", "values": [float]}]}` ou `None` se o bloco não for um xychart parseável (flowchart, sintaxe corrompida). Suporta: título com aspas, `x-axis [..]` com rótulos, `y-axis "Label"` com faixa opcional `0 --> 100`, múltiplas séries `line`/`bar`.
- `render_chart(chart: dict, style: dict, output_path: str) -> None` — renderiza PNG via matplotlib usando **API orientada a objetos com backend Agg** (`matplotlib.figure.Figure` + `FigureCanvasAgg`), **nunca `pyplot`**: a renderização roda em worker threads e o estado global do pyplot/backend Tk causaria os mesmos segfaults da regra de threading já documentada no projeto.
- Mapeamento do dicionário `style` (vindo das vars da GUI, chaves e valores atuais preservados — sem migração de settings):
  - `chart_type` "Linha"/"Barra" → sobrescreve o tipo de todas as séries (comportamento atual mantido).
  - `chart_color` ("Padrão" → ciclo de cores default do matplotlib; demais → hex já mapeado hoje).
  - `chart_width`/`chart_height` px → `figsize=(w/100, h/100)`, `dpi=100` (PNG com dimensão exata em px).
  - `chart_bg_color` ("Transparente" → `savefig(transparent=True)`; demais → `facecolor` hex).
  - `chart_text_color` → cor de título, rótulos, ticks e eixos.
  - `chart_font` (valores atuais são pilhas CSS, ex. `"Arial, Helvetica, sans-serif"`) → usa a primeira família da pilha (strip de aspas) como `font.family`, com fallback silencioso do matplotlib (DejaVu Sans embutido) se não existir no SO.

### 2. `gui/main_view.py::_render_mermaid_charts` (reescrita interna, contrato preservado)

Mesma assinatura e mesmo retorno `(markdown_modificado, temp_dir | None)`. Por bloco ```` ```mermaid ````: `normalize_mermaid` → `parse_xychart` → sucesso: `render_chart` para PNG no temp dir e substituição por `![Gráfico](...)`; falha: bloco permanece como está (código), com uma linha de log avisando. Some todo o código Playwright/HTML/screenshot, o import condicional de `playwright.sync_api` e as mensagens "Execute 'playwright install'".

### 3. `gui/style_settings_view.py::_render_preview_thread`

Substitui o pipeline Playwright pela chamada direta a `render_chart` com um gráfico de exemplo fixo (mesmos dados de hoje). Prévia fica mais rápida; textos "Gerando prévia com Playwright..." atualizados.

### 4. PDF via Typst (`gui/main_view.py::_export_report_thread`, ramo `.pdf`)

1. Markdown processado (com links PNG) tem os caminhos de imagem reescritos de absolutos para **relativos ao temp dir** dos gráficos (necessário para o `root` do Typst funcionar igual em Linux e Windows).
2. `pypandoc.convert_text(md, 'typst', format='gfm+hard_line_breaks')` gera o corpo em markup Typst.
3. Um template novo `templates/report_template.typ` fornece o preâmbulo: página A4 com margens (2.5cm/2cm), numeração de rodapé `X / Y` (`#set page(numbering: ...)`), fonte padrão, estilos de heading/tabela/código, e a capa (título "Relatório Técnico de Auditoria Zabbix", autor/empresa, data — placeholders `__AUTHOR__`/`__DATE__` etc. substituídos em Python, mesmo padrão do template HTML atual) seguida de `#pagebreak()`.
4. Preâmbulo + corpo são gravados como `.typ` dentro do temp dir e compilados com `typst.compile(entrada, output=destino, root=temp_dir)`.
5. Bloco `finally` continua removendo o temp dir (regra existente).

**Gate de versão do pandoc**: o writer Typst exige pandoc ≥ 3.1.7. Antes da conversão, checar `pypandoc.get_pandoc_version()`; se ausente **ou** antigo, chamar `pypandoc.download_pandoc()` (fallback que o app já usa hoje para pandoc ausente) e logar.

### 5. Dependências e Dockerfile

- `requirements.txt`: remove `playwright==1.61.0`; adiciona `matplotlib` e `typst` com versões fixadas (resolver a última estável no momento da implementação, via PyPI).
- `Dockerfile`: remove `pip install playwright && playwright install --with-deps chromium`; remove `pandoc` do `apt-get install` (o do Debian é 2.x, sem writer Typst) e adiciona `RUN python -c "import pypandoc; pypandoc.download_pandoc()"` após o pip install. A imagem encolhe substancialmente (sem Chromium).
- Deleta `templates/mermaid_template.html`.

### 6. Documentação

- `README.md`: remove o passo `playwright install`; atualiza a descrição de exportação PDF (Typst em vez de Chromium/Playwright) e a de gráficos; atualiza a árvore de estrutura (novo `core/chart_renderer.py`, `templates/report_template.typ`, sem `mermaid_template.html`).
- `TECHNICAL_REFERENCE.md`: reescreve a seção 5 (renderização/exportação) para o novo pipeline; remove menções a Playwright; gotcha novo: usar somente API OO + Agg do matplotlib em threads (nunca pyplot).
- `CLAUDE.md`: atualiza comandos (sem `playwright install`), a seção do pipeline de export, e gotchas (remove os de browser; adiciona Agg/pyplot e o gate de versão do pandoc).

## Tratamento de erros

- Bloco Mermaid não parseável → permanece como bloco de código no documento + log de aviso (não aborta o export).
- Falha na compilação Typst ou pandoc → log "danger" + diálogo de erro, mesmo padrão do caminho pandoc atual.
- Pandoc ausente/antigo → auto-download com log (comportamento estendido do fallback atual).

## Testes

`tests/test_chart_renderer.py` (unittest, stdlib + matplotlib):

- `parse_xychart`: sintaxe canônica do prompt; variantes alucinadas (`lineChart`, `data: [`, `bar [`) após `normalize_mermaid`; faixa `0 --> 100` no y-axis; múltiplas séries; flowchart e lixo → `None`.
- `render_chart`: smoke test — gera PNG real em temp dir (arquivo existe, > 0 bytes), com estilo default e com overrides (barra, transparente, dimensões), sem display (Agg).
- Reescrita de caminhos absolutos → relativos para o Typst.
- O pipeline pandoc→typst→pdf não entra na suíte automatizada (depende de binário pandoc e rede p/ download) — verificação manual/smoke no fim da implementação.

GUI (prévia, export completo) permanece verificação manual, como nas features anteriores.

## Riscos e mitigação

- **Writer Typst do pandoc + imagens**: caminhos relativos + `root=temp_dir` no `typst.compile` evitam problemas de path cross-platform.
- **Fidelidade visual do PDF**: capa e estilos refeitos em Typst; validar com um export real de cache antes de dar por concluído.
- **Fonte configurada inexistente no SO**: matplotlib faz fallback automático para DejaVu Sans (embutida no wheel) — sem crash.

## Fora de escopo / Futuro

- Renderização de diagramas Mermaid não-xychart (flowcharts etc.).
- Tema/estilização avançada dos PDFs além da paridade com o layout atual.
