# Contributing — FinTech MLOps Platform

## Branches

- `main` est **protégée** : pas de push direct.
- Crée une branche depuis `main` avec le format :
  ```
  feat/<rôle>-<sujet>
  ```
  Exemples :
  - `feat/role1-auth-service`
  - `feat/role3-kube-manifests`
  - `feat/role4-xgboost-benchmark`
  - `feat/role5-fastapi-serving`

## Commits — Conventional Commits

Utilise le format [Conventional Commits](https://www.conventionalcommits.org/) :

```
<type>(<scope>): <description>
```

Types courants :
| Type       | Usage                                    |
|------------|------------------------------------------|
| `feat`     | Nouvelle fonctionnalité                  |
| `fix`      | Correction de bug                        |
| `docs`     | Documentation uniquement                 |
| `ci`       | CI/CD, workflows GitHub Actions          |
| `refactor` | Refactoring sans changement fonctionnel  |
| `test`     | Ajout ou modification de tests           |
| `chore`    | Maintenance (dépendances, config, etc.)  |

Exemples :
```
feat(auth): add JWT token validation
fix(risk): handle null probability from /predict
ci(backend): add SonarCloud analysis step
docs(readme): add architecture diagram
```

## Pull Requests

- **Une PR par fonctionnalité** (pas de PR géantes multi-sujets).
- Remplis le template de PR (description, type, checklist).
- Au moins **1 review** avant le merge.
- Le reviewer vérifie :
  - Pas de secrets dans le code
  - Build et tests passent
  - La documentation est à jour

## Secrets

- **JAMAIS** de mot de passe, token ou clé dans le code.
- Utilise `.env` (non commité) + `.env.example` (commité avec des valeurs factices).
- Les secrets Kubernetes réels sont créés en local, pas dans Git.

## Images Docker

Chaque service doit respecter la [checklist d'image](docs/conventions.md) :
1. Démarre avec une seule commande
2. Port documenté
3. `/health` et `/metrics` exposés
4. Configuration via variables d'environnement uniquement
