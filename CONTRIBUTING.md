## 🤖 **Guia de Fluxo Git - Drone Waste Monitoring**

Este documento explica como trabalhar com branches, Pull Requests e o que as
Actions fazem automaticamente neste repositório.

### ➡️ **Visão geral do fluxo**

```
feature/xxx  →  develop  →  main
   (você)      (revisão)   (release)
```

1. Você cria uma branch a partir de `main` para trabalhar em algo novo.
2. Ao dar push, um PR para `develop` é aberto automaticamente.
3. Depois de aprovado e mesclado, um PR de `develop` para `main` é aberto
   automaticamente.
4. Depois de aprovado e mesclado esse segundo PR, a `main` está atualizada.

Você nunca precisa abrir PR manualmente (as Actions fazem isso por você).
O que continua manual é: **revisar e clicar em "Merge"**.

### ✏️ **Convenção de nomes de branch**

Só é possível criar (e dar push de) branches com um destes prefixos:

| Prefixo     | Quando usar                                  |
|-------------|-----------------------------------------------|
| `feature/`  | Nova funcionalidade                            |
| `fix/`      | Correção de bug                                |
| `hotfix/`   | Correção urgente                               |

Exemplos válidos: `feature/tela-deteccao`, `fix/erro-conexao-drone`.

Se você tentar dar push de uma branch com outro nome (ex: `teste123`,
`minha-branch`), o GitHub vai recusar a criação da branch remota. Isso é
proposital, é uma regra configurada no repositório (Ruleset), não um bug.

### ✨ **Convenção de commits**
 
Cada commit deve começar com um prefixo indicando o tipo de mudança:
 
| Prefixo    | Quando usar                                         |
|------------|------------------------------------------------------|
| `feat:`    | Nova funcionalidade                                   |
| `fix:`     | Correção de bug                                       |
| `docs:`    | Alteração só em documentação (README, este guia, etc.)|
| `refactor:`| Mudança no código que não altera comportamento        |
| `test:`    | Adição ou ajuste de testes                            |
| `chore:`   | Tarefa de manutenção (dependências, config, CI)       |
 
Exemplos:
```
feat: adiciona tela de telemetria do drone
fix: corrige leitura de bateria retornando null
docs: atualiza instruções de instalação no README
chore: ajusta permissões do workflow de PR
```
 
Mensagem curta, no imperativo, sem ponto final no fim.

### 🔄️ **Passo a passo do dia a dia**

1. Atualize sua `main` local:
   ```
   git checkout main
   git pull
   ```
2. Crie sua branch:
   ```
   git checkout -b feature/nome-da-tarefa
   ```
3. Trabalhe, commite e dê push:
   ```
   git push -u origin feature/nome-da-tarefa
   ```
4. Um PR para `develop` aparece sozinho na aba **Pull Requests** do GitHub.
5. Peça para o outro dev revisar e aprovar (é obrigatório, ver seção abaixo).
6. Clique em **Merge pull request**.
7. Um novo PR de `develop` para `main` aparece sozinho.
8. Revise, aprove e mescle esse PR quando quiser lançar a versão em `main`.

### 🤔 **O que cada Action faz**

| Arquivo                        | Quando roda                          | O que faz                                   |
|---------------------------------|---------------------------------------|----------------------------------------------|
| `ci-feature-develop.yml`       | Push em `feature/**`, `fix/**`, `hotfix/**` | Abre PR da sua branch para `develop`        |
| `ci-develop-main.yml`          | Merge de PR em `develop`             | Abre PR de `develop` para `main`             |
| `ci-main-release.yml`          | Merge de PR em `main`                | Escreve um resumo dizendo que a main foi atualizada (aba Actions → clique na execução → "Summary") |

Nenhuma dessas Actions roda testes, instala dependências ou faz build — elas
só cuidam da abertura de PR e do aviso. Validação de código (testes, lint)
será adicionada depois.

### 🔒 **Regras de proteção configuradas**

- **`main` exige Pull Request**, não é possível dar push direto nela.
- **`main` exige pelo menos 1 aprovação** antes do merge liberar.
- **Aprovação é exigida no último commit enviado**, se alguém aprovar e
  depois o autor subir mais um commit, a aprovação é invalidada e precisa
  ser feita de novo.
- **Nomes de branch fora do padrão `feature/`, `fix/`, `hotfix/` (e as
  próprias `main`/`develop`) não podem ser criados** no GitHub.
- **Force push (`git push -f`) é bloqueado** em todas as branches, para
  evitar que o histórico de commits de alguém seja sobrescrito sem querer.

### ⚠️ **Erros comuns**

**"remote: error: GH013: Repository rule violations found"**

> Você tentou dar push com um nome de branch fora do padrão, ou tentou dar
push direto na `main`. Renomeie sua branch local (`git branch -m nome-certo`)
e tente de novo.

**PR não aparece automaticamente depois do push**

> Confira na aba **Actions** do GitHub se o workflow `ci-feature-develop.yml`
rodou e terminou com sucesso (ícone verde). Se falhou, o erro mais comum é
falta de permissão — confira em `Settings → Actions → General → Workflow
permissions` se está marcado "Read and write permissions" e "Allow GitHub
Actions to create and approve pull requests".

**Botão de "Merge" aparece cinza/bloqueado**

> Falta pelo menos 1 aprovação de outra pessoa no PR. Quem abriu o PR não pode
aprovar o próprio PR.

**"gh pr create" falhou dizendo que não há commits entre as branches**

>Normal quando não há nada novo em `develop` para levar pra `main` (ou nada
novo na sua branch para levar pra `develop`). Não é um erro real, só significa
que não havia PR o que abrir.