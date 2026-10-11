# Contributing Guidelines — FinTech MLOps Platform

> 📘 **New to GitHub Issues and PRs?** Check our comprehensive step-by-step [Team Workflow Guide](docs/workflow-guide.md) to learn how to pick an issue, branch, commit, and link PRs with `Closes #ID`.

## Branching Strategy

- The `main` branch is **protected**: direct pushes are prohibited.
- Always branch off `main` using the following naming standard:
  ```
  feat/<role>-<topic>
  ```
  Examples:
  - `feat/role1-auth-service`
  - `feat/role3-kube-manifests`
  - `feat/role4-xgboost-benchmark`
  - `feat/role5-fastapi-serving`

## Commit Messages — Conventional Commits

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <description>
```

Common types:
| Type       | Description                              |
|------------|------------------------------------------|
| `feat`     | A new feature                            |
| `fix`      | A bug fix                                |
| `docs`     | Documentation changes only               |
| `ci`       | CI/CD workflows and pipelines            |
| `refactor` | Code refactoring without behavior change |
| `test`     | Adding or updating tests                 |
| `chore`    | Build tasks, dependencies, configs       |

Examples:
```
feat(auth): add JWT token validation
fix(risk): handle null probability response from /predict
ci(backend): add SonarCloud analysis step
docs(readme): add architecture diagram
```

## Pull Requests (PR)

- **One PR per feature** (avoid large monolithic PRs spanning multiple components).
- Fill out the PR template thoroughly (description, type, checklist).
- Require at least **1 peer review approval** before merging.
- Reviewer verification checklist:
  - Zero secrets or sensitive data in code or configuration
  - Build passes and all tests succeed
  - Relevant documentation is up to date

## Secrets & Security

- **NEVER** commit real passwords, tokens, private keys, or credentials.
- Use local `.env` (git-ignored) with reference in `.env.example` (committed with dummy values).
- Kubernetes real secrets must be generated locally or injected securely in CI/CD, never stored in Git.

## Docker Image Requirements

Every containerized service must adhere to the [Service Image Checklist](docs/conventions.md):
1. Starts cleanly with a single command.
2. Listens on a documented, dedicated port.
3. Exposes `/health` and `/metrics` endpoints (`/actuator/health` and `/actuator/prometheus` for Spring Boot).
4. Configured purely through environment variables with zero hardcoded credentials.
