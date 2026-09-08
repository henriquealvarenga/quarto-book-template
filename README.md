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
      `site-url` e `repo-url`
- [ ] `index.qmd`: prefácio (sobre o livro, públicos)
- [ ] `epigrafes.qmd`: contracapa de epígrafes — ou remova do sumário se não usar
- [ ] `apresentacao.qmd`: apresentação — ou remova do sumário se não usar
- [ ] `creditos.qmd`: título, repo, ano, crédito da imagem de capa, BibTeX
- [ ] `images/capa.html`: editar título/subtítulo/edição e rodar `./code/make_cover.sh`
      (gera `images/capa.jpg`, **1600×2500 px**, via Chrome headless). Alternativa:
      editar `images/capa.pxd` no **Pixelmator** e exportar como `images/capa.jpg`
- [ ] `images/favicon.png` (**256×256**, foto do autor) e `apple-touch-icon.png`
      (**180×180**, opaco): já vêm preenchidos e são os mesmos em todos os livros
- [ ] `references/references.bib`: substituir a entrada-exemplo pela bibliografia real
- [ ] `capitulos/`, `casos/`, `atividades/`, `apendices/`: substituir os exemplos
- [ ] Renomear a parte/pasta `capitulos/parte-1-exemplo/` conforme o conteúdo

O **autor** (Henrique Alvarenga / ORCID / UFSJ), a **licença** (CC BY-NC-SA 4.0),
o **footer** (identificação profissional CFM, centralizada), as **fontes**, o
**tema**, o **favicon** e o `_language-pt.yml` já vêm preenchidos — em geral não
precisam mudar.

## Estrutura de pastas (sempre presentes)

| Pasta | Conteúdo |
|---|---|
| `capitulos/` | capítulos do livro, organizados em `parte-N-nome/NN-slug.qmd` |
| `apendices/` | material complementar (listado em `appendices:` do `_quarto.yml`) |
| `atividades/` | exercícios e dinâmicas didáticas |
| `casos/` | casos clínicos / roteiros de entrevista |
| `references/` | `references.bib` + `csl_styles/` (ABNT, Vancouver) + `PDFs/` (gitignored) |
| `fonts/` | fontes self-hosted (.woff2) referenciadas no `styles.css` |
| `images/` | `capa.html` (fonte da capa) + `capa.jpg` (1600×2500, gerada) + `capa.pxd` (modelo Pixelmator alternativo) + `favicon.png` (256×256) + figuras |
| `code/` | scripts Python de validação bibliográfica (usados pelo CI) + `make_cover.sh` |

## Arquivos de estilo (não editar por projeto — manter sincronizados com o template)

- `theme-editorial.scss` — tema "paper": paleta, tipografia serif/sans, layout.
- `styles.css` — `@font-face` das fontes + largura editorial, notas de rodapé
  compactas, capa, contracapa de epígrafes (`.epigrafes`) e classes da página de
  créditos (`.contact-links`, `.about-section`, `.tech-stack`, `.cover-credit-thumb`, …).
- `_language-pt.yml` — localização pt-BR completa (callouts, crossref, busca, etc.).
- `.github/workflows/publish.yml` e `code/*.py` — CI e validadores (pins de
  Quarto e Python acompanham a máquina do autor).

> ⚠️ Como este é um **template** (cópia), melhorias no tema feitas num projeto
> devem ser levadas de volta a este template para os próximos projetos. Para
> sincronizar projetos já existentes, copie os arquivos acima. Última
> sincronização: 08/09/2026, a partir do livro *Memória* (rodapé CFM, notas de
> rodapé compactas, contracapa de epígrafes, `*.pdf` ignorado, Quarto 1.10.18).

## Build local

```bash
quarto render --to html            # gera _book/
python code/validate_bib.py --no-doi   # valida a bibliografia (offline)
quarto preview                     # servidor local com hot-reload
```

## Publicação

`push` para `main` dispara o workflow (`validate-bib → build → deploy`) e publica
em `https://henriquealvarenga.com/<repo>/` (o GitHub Pages do usuário usa o
domínio próprio). Pull requests apenas validam, não publicam.

---

Padrão da casa — Henrique Alvarenga da Silva · UFSJ · Curso de Medicina.
Licença do conteúdo dos livros: CC BY-NC-SA 4.0.
