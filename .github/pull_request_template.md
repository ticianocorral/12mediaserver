# Pull Request — TicianoFlix

## 📦 Tipo de mudança (obrigatório — define a versão)

> Marque **um** — o bump de versão automático usa esta informação.

- [ ] **`BREAKING CHANGE`** → nova versão **MAJOR** (ex: 1.5 → 2.0)
  - Mudança incompatível: API diferente, remoção de recurso, formato de dados novo
- [ ] **`feat:`** → nova versão **MINOR** (ex: 1.5 → 1.6)
  - Nova funcionalidade, novo recurso visível ao usuário
- [ ] **`fix:`** → nova versão **PATCH** (ex: 1.5 → 1.5.1)
  - Correção de bug, ajuste visual, melhoria sem novo recurso
- [ ] **`docs:` / `chore:` / `refactor:`** → **NÃO** altera versão (sem bump)

## 📝 Descrição

<!-- O que este PR faz e por quê -->

## ✅ Checklist obrigatório

- [ ] **README atualizado** — nova entrada no topo do [Changelog](../README.md#changelog)
- [ ] **Changelog do app atualizado** — `_CHANGELOG` no `index.html`
- [ ] **Badge de versão atualizado** — `<span class="logo-version">` no `index.html`
- [ ] Testado localmente (servidor + player)

> 💡 **Dica:** rode `./bump-version.sh <major|minor|patch|none> "título do changelog"` — ele atualiza badge, changelog JS e README de uma vez.

## 🧪 Como testar

<!-- Passos para reproduzir/validar -->
