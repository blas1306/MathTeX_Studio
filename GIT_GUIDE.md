# Git Guide for MathTeX Project

## 🧠 Mental Model

Git has three levels:

1. **Working Directory** → your files
2. **Staging Area** → what will be committed
3. **Repository (Commits)** → saved history

---

## 🔥 Basic Workflow

```bash
git status
git add .
git commit -m "message"
git push
```

---

## 📌 What Each Command Does

### `git status`

Shows what changed.

### `git add`

Prepares files for commit.

```bash
git add file.py
git add .
```

### `git commit`

Saves changes.

```bash
git commit -m "fix: improve var indexing"
```

### `git push`

Uploads changes to GitHub.

---

## 🌿 Branches

A branch = an independent line of work.

### Create a branch

```bash
git checkout -b feature/my-feature
```

### Switch branch

```bash
git checkout main
```

### List branches

```bash
git branch
```

---

## 🔄 Merge

```bash
git checkout main
git merge feature/my-feature
```

---

## ⚠️ Merge Conflicts

You may see:

```
<<<<<<< HEAD
=======
>>>>>>> branch
```

Fix manually, then:

```bash
git add file.py
git commit
```

---

## 🚀 Push Branch

First time:

```bash
git push -u origin feature/my-feature
```

Later:

```bash
git push
```

---

## 🧹 Delete Branch

Local:

```bash
git branch -d feature/my-feature
```

Remote:

```bash
git push origin --delete feature/my-feature
```

---

## 🔄 Pull Updates

```bash
git pull
```

---

## 🧠 Real Workflow

### Add feature

```bash
git checkout -b feature/demo
git add .
git commit -m "feat: add demo"
git push -u origin feature/demo
```

### Merge to main

```bash
git checkout main
git pull
git merge feature/demo
git push
```

### Clean up

```bash
git branch -d feature/demo
git push origin --delete feature/demo
```

---

## 📝 Commit Messages

Use structured messages:

* `feat:` new feature
* `fix:` bug fix
* `docs:` documentation
* `refactor:` code change
* `test:` tests

Examples:

```bash
git commit -m "feat: add physics demo"
git commit -m "fix: improve pipeline stability"
git commit -m "docs: update README"
```

---

## ⚠️ Common Mistakes

* ❌ Working only on main
* ❌ Huge commits
* ❌ Uploading temporary files

---

## 🧠 Useful Commands

### History

```bash
git log --oneline
```

### Differences

```bash
git diff
```

### Restore file

```bash
git restore file.py
```

---

## 💬 Final Insight

Git is not about commands.

It is about:

> saving work + organizing changes

---