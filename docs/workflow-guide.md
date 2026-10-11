# Team Collaboration & GitHub Workflow Guide

Welcome to the **FinTech MLOps Platform** team! This guide walk you through our standard day-to-day workflow: how to pick up an assigned task, code in an isolated branch, submit a Pull Request (PR), and automatically close your issue upon merging.

Following this workflow ensures no code gets lost, prevents merge conflicts, and maintains high project quality for our final academic deliverable.

---

## 🔁 Overview: The 7-Step Development Lifecycle

```
1. Pick Issue  ──>  2. Create Branch  ──>  3. Code & Commit  ──>  4. Push Branch
      │
      └──────────────────────────────────────────────────────────────┐
                                                                     ▼
7. Sync Local Main  <──  6. Review & Merge  <──  5. Open Pull Request (Closes #ID)
```

---

## Step 1: Pick Your Assigned Issue

1. Go to the repository's [Issues Tab](https://github.com/Oubay-S/fintech-mlops-platform/issues) or the [Project Kanban Board](https://github.com/users/Oubay-S/projects/1).
2. Filter by your role label:
   - `role-1` : Backend (Spring Boot)
   - `role-2` : Frontend & Delivery
   - `role-3` : DevOps / MLOps
   - `role-4` : ML Training
   - `role-5` : ML Serving
3. Find your current task for the milestone (e.g., *Issue #3: `[Role 1] Implement Customer & Transaction services...`*).
4. Assign yourself to the issue under **Assignees** and move the card to **In Progress** on the Project board.

---

## Step 2: Create a Dedicated Feature Branch

Always ensure your local `main` branch is clean and up to date before creating a new branch:

```bash
# 1. Switch to main
git checkout main

# 2. Pull the latest approved changes from GitHub
git pull origin main

# 3. Create and switch to your new branch
# Naming rule: feat/<role>-<short-description>
git checkout -b feat/role1-customer-transactions
```

> ⚠️ **Rule:** Never develop directly on the `main` branch. Direct pushes to `main` are blocked by branch protection rules.

---

## Step 3: Develop, Test, and Commit

Make your code changes within your assigned directory (`services/`, `ml/`, `frontend/`, etc.).

### Run Local Checks First
Before committing, make sure your code builds and passes tests:
- **Java (Role 1):** `./mvnw clean test`
- **Python (Roles 4 & 5):** `pytest`
- **React (Role 2):** `npm run build`

### Commit using Conventional Commits
Stage your changed files and write clear commit messages:

```bash
git add .
git commit -m "feat(customer): add REST controller and postgres repository"
```

Common commit prefixes:
- `feat(...)`: New feature or endpoint
- `fix(...)`: Bug fix
- `test(...)`: Adding unit or integration tests
- `docs(...)`: Documentation updates
- `refactor(...)`: Code cleanup with no functional changes

> 🔒 **Security Reminder:** Never commit `.env` files, database passwords, or real API tokens. Use `.env.example` as a template.

---

## Step 4: Push Your Branch to GitHub

Push your local feature branch to the remote repository:

```bash
git push -u origin feat/role1-customer-transactions
```

---

## Step 5: Open a Pull Request (PR) & Link Your Issue

1. Open the repository on GitHub: [Oubay-S/fintech-mlops-platform](https://github.com/Oubay-S/fintech-mlops-platform).
2. Click the green button: **"Compare & pull request"**.
3. Fill out the pre-populated PR template:
   - **Title:** Same as your feature or issue (e.g., `feat(customer): implement customer and transaction services`).
   - **Description:** Provide a 2-3 sentence overview of what was built or changed.
   - **Automatic Issue Linking (CRITICAL):** In the description, type:
     ```markdown
     Closes #3
     ```
     *(Replace `3` with your actual Issue number)*.
   - Complete the **Quality & Security Checklist**.
4. Click **"Create pull request"**.

---

## Step 6: Peer Review & Merge

1. Request a review from at least one teammate (e.g., your role partner or @Oubay-S for infra/DevOps).
2. Once the reviewer approves the changes:
   - Click **"Merge pull request"** (or **"Squash and merge"**).
   - Click **"Confirm merge"**.
   - Click **"Delete branch"** to keep the remote repository clean.
3. **Magic Result:** Because you included `Closes #3`, GitHub automatically marks Issue #3 as **Closed (Done)** and moves it on the Kanban board!

---

## Step 7: Update Your Local Environment

After your PR is merged, return to your local terminal, switch back to `main`, and pull the merged code:

```bash
# Switch back to main
git checkout main

# Fetch latest merged code
git pull origin main

# Delete your local feature branch (optional cleanup)
git branch -d feat/role1-customer-transactions
```

You are now ready to pick up your next issue from Step 1!

---

## ❓ Frequently Asked Questions (FAQ)

### What if I encounter merge conflicts?
If someone else merged changes to `main` that affect files you touched, update your branch:
```bash
git checkout feat/your-branch
git fetch origin
git merge origin/main
# Resolve any conflicting lines in your IDE, then:
git add .
git commit -m "chore: resolve merge conflicts with main"
git push origin feat/your-branch
```

### Can I link multiple issues to a single PR?
Yes, simply list them on separate lines in your PR description:
```markdown
Closes #3
Closes #4
```

### Who do I contact if I need infra, database, or MLflow help?
Tag **@Oubay-S** (Role 3 DevOps/MLOps) directly in your issue or PR comment.
