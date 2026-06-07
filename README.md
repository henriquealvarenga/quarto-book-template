# Quarto Book Template

Template (esqueleto) padronizado para os livros didáticos em **Quarto book** —
tema editorial "paper" (Inter + Playfair Display + JetBrains Mono, self-hosted),
configuração, estrutura de pastas e workflow de publicação no GitHub Pages já
prontos. Serve para que cada livro novo nasça **idêntico** em estilo e organização.

## Como começar um livro novo

**Opção A — GitHub (recomendada):** clique em **"Use this template" → Create a new
repository** (ou `gh repo create meu-livro --template henriquealvarenga/quarto-book-template`).
Depois clone o novo repo.

**Opção B — cópia local:** copie esta pasta para um novo diretório e rode `git init`.

Em seguida, em **Settings → Pages → Build and deployment → Source: GitHub Actions**
(pré-requisito do workflow `.github/workflows/publish.yml`).

## Checklist do que trocar (procure por `<TODO>`)

```
grep -rn "TODO" . --include="*.qmd" --include="*.yml"
```

- [ ] `_quarto.yml`: `title`, `subtitle`, `edition`, `description`, `keyword`,
      `repo-url` (3 ocorrências: repo-url, footer, etc.)
- [ ] `index.qmd`: prefácio (sobre o livro, públicos)
- [ ] `apresentacao.qmd`: apresentação — ou remova do sumário se não usar
- [ ] `creditos.qmd`: título, repo, ano, crédito da imagem de capa, BibTeX
- [ ] `images/capa.pxd`: editar o modelo no **Pixelmator** (título/subtítulo/autor) e **exportar** como `images/capa.png` (padrão **1600×2500 px**), substituindo o placeholder
- [ ] `images/favicon.png`: substituir o favicon placeholder (**512×512 px**)
- [ ] `references/references.bib`: substituir a entrada-exemplo pela bibliografia real
- [ ] `capitulos/`, `casos/`, `atividades/`, `apendices/`: substituir os exemplos
- [ ] Renomear a parte/pasta `capitulos/parte-1-exemplo/` conforme o conteúdo

O **autor** (Henrique Alvarenga / ORCID / UFSJ), a **licença** (CC BY-NC-SA 4.0),
o **footer**, as **fontes**, o **tema** e o `_language-pt.yml` já vêm preenchidos —
em geral não precisam mudar.

## Estrutura de pastas (sempre presentes)

| Pasta | Conteúdo |
|---|---|
| `capitulos/` | capítulos do livro, organizados em `parte-N-nome/NN-slug.qmd` |
| `apendices/` | material complementar (listado em `appendices:` do `_quarto.yml`) |
| `atividades/` | exercícios e dinâmicas didáticas |
| `casos/` | casos clínicos / roteiros de entrevista |
| `references/` | `references.bib` + `csl_styles/` (ABNT, Vancouver) + `PDFs/` (gitignored) |
| `fonts/` | fontes self-hosted (.woff2) referenciadas no `styles.css` |
| `images/` | `capa.pxd` (modelo Pixelmator editável da capa) + `capa.png` (1600×2500, exportada) + `favicon.png` (512×512) + figuras |
| `code/` | scripts Python de validação bibliográfica (usados pelo CI) |

## Arquivos de estilo (não editar por projeto — manter sincronizados com o template)

- `theme-editorial.scss` — tema "paper": paleta, tipografia serif/sans, layout.
- `styles.css` — `@font-face` das fontes + classes da página de créditos
  (`.contact-links`, `.about-section`, `.tech-stack`, `.cover-credit-thumb`, …).
- `_language-pt.yml` — localização pt-BR completa (callouts, crossref, busca, etc.).

> ⚠️ Como este é um **template** (cópia), melhorias no tema feitas num projeto
> devem ser levadas de volta a este template para os próximos projetos. Para
> sincronizar projetos já existentes, copie os 3 arquivos acima.

## Build local

```bash
quarto render --to html            # gera _book/
python code/validate_bib.py --no-doi   # valida a bibliografia (offline)
quarto preview                     # servidor local com hot-reload
```

## Publicação

`push` para `main` dispara o workflow (`validate-bib → build → deploy`) e publica
em `https://henriquealvarenga.github.io/<repo>/`. Pull requests apenas validam,
não publicam.

---

Padrão da casa — Henrique Alvarenga da Silva · UFSJ · Curso de Medicina.
Licença do conteúdo dos livros: CC BY-NC-SA 4.0.
