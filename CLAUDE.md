```markdown
# Local File Manager — AI Coding Guide

> A local macOS file management and organization tool. Built with Python/FastAPI.
> This guide controls how AI assistants generate code for this project.
> Read this file completely before writing any code.

---

## App Purpose (Domain Context)

This app is a **local file management and organization tool** for macOS.
Core capabilities:
1. Scan and analyze local directory structures and file metadata
2. Rename files based on content analysis and/or creation date
3. Move files automatically based on predefined rules and folder structures
4. All operations run 100% locally — no cloud, no external storage, no accounts

---

## Tech Stack

- **Backend:**         FastAPI (Python), strict Type Hints throughout
- **Frontend:**        Jinja2 Templates + Tailwind CSS (CDN) + Alpine.js
- **Database:**        SQLite via `aiosqlite` (Async) mit aktiviertem WAL-Mode (Write-Ahead Logging) und `timeout=10.0` zur Vermeidung von Concurrency-Locks + ChromaDB (optional).
- **Deployment:**      Local macOS only — Terminal via uvicorn or PyInstaller as .app
- **Validation:**      Pydantic v2 (built into FastAPI)
- **State:**           Alpine.js — no React, no Vue, no build step
- **File Operations:** Python Standard Library only (pathlib, shutil, os)
- **AI/Analysis:**     Ollama (local) or Mistral API (optional, for content analysis)

---

## Project Structure

```text
project/
├── main.py               # FastAPI app entry point (root level for simple startup)
├── api/                  # Route definitions (scan, rename, move, rules)
├── core/                 # Business logic
│   ├── analyzer.py       # File & directory analysis
│   ├── renamer.py        # Rename logic (date-based, content-based)
│   └── mover.py          # Move logic based on rules
├── models/               # Pydantic request/response models
├── utils/                # Shared helpers (path validation, hashing)
├── templates/            # Jinja2 HTML templates
├── static/               # CSS, JS, icons
├── data/
│   └── filemanager.db    # SQLite database (never commit this)
├── features/             # Feature specifications
│   ├── INDEX.md          # Feature status overview
│   └── PROJ-X-name.md    # Individual feature specs
├── docs/
│   └── PRD.md            # Product Requirements Document
├── .gitignore            # venv/, data/, __pycache__/, *.db
├── requirements.txt
└── CLAUDE.md             # This file
```

---

## Development Workflow

1. `/requirements` — Create feature spec from idea, focus on file operation logic
2. `/architecture` — Design Python module structure and SQLite schema (no code)
3. `/backend`      — Build FastAPI endpoints, file processing, Pydantic models
4. `/frontend`     — Build Jinja2 templates with Tailwind + Alpine.js
5. `/qa`           — Test file operations, validate DB integrity, check error handling
6. `/deploy`       — Verify local startup, run PyInstaller if .app needed

---

## Feature Tracking

All features tracked in `features/INDEX.md`.
Every skill reads it at start and updates status when done.
Feature specs live in `features/PROJ-X-name.md`.

> If `features/INDEX.md` does not exist yet: run `/requirements` first to generate it.

---

## Key Conventions

- **Feature IDs:**        PROJ-1, PROJ-2, etc. (sequential)
- **Commits:**            `feat(PROJ-X): description` / `fix(PROJ-X): description`
- **Single Responsibility:** One feature per spec file
- **Async First:**        All file I/O must use async/await or FastAPI BackgroundTasks
- **Paths:**              Always use `pathlib.Path` — never raw strings for file paths
- **Human-in-the-loop:**  Destructive operations (rename, move, delete) MUST show
                          a confirmation step in the UI before execution

---

## ⛔ Hard Rules — Never Violate

- NEVER use React, Node.js, npm, or any JS framework for backend logic
- NEVER execute rename/move/delete without explicit user confirmation in the UI
- NEVER use synchronous blocking code for file I/O — always async or BackgroundTasks
- NEVER hardcode absolute file paths — always use pathlib.Path and user-provided input
- NEVER skip Pydantic validation on file path inputs (path traversal is a real risk)
- NEVER store the SQLite database inside the source folders — always in /data
- NEVER recreate Alpine.js reactivity with vanilla JS — use x-data, x-bind, x-on
- NEVER commit data/, venv/, __pycache__/ or any .db file to version control
- NEVER use synchronous SQLite connections (like standard `sqlite3`) inside async routes or BackgroundTasks. ALWAYS use `aiosqlite` to prevent "database is locked" errors during parallel file processing.
---

## Build & Run Commands

```bash
# One-time setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Development server (with auto-reload)
uvicorn main:app --reload --port 8000

# Code quality (optional but recommended)
ruff check .
black .

# Production / Packaging (optional)
pyinstaller --onefile main.py
```

---

## Local Deployment Checklist

- [ ] App starts cleanly via `uvicorn` after fresh `pip install -r requirements.txt`
- [ ] SQLite database file is located in `/data`, not in source folders
- [ ] No hardcoded paths pointing to any developer's home directory
- [ ] All destructive operations have a confirmation dialog in the UI
- [ ] `.gitignore` covers `venv/`, `data/`, `__pycache__/`, `*.db`
- [ ] PyInstaller `.app` tested (only if standalone app is required)

---

## Product Context

> If `docs/PRD.md` does not exist yet: run `/requirements` first to generate it.

@docs/PRD.md

## Feature Overview

> If `features/INDEX.md` does not exist yet: run `/requirements` first to generate it.

@features/INDEX.md
```
