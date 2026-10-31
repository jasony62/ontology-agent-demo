# AGENTS.md

## Working scope（先读）

**本机唯一权威 checkout 是本文件所在目录：`/Users/yangyue/projects/ontology-agent-demo`。**

本机还可能存在其它名为 `ontology-agent-demo` 的目录副本。**它们属于其它用户或其它用途，在本项目范围内一律视为不存在**——不得查找、列举、读取、diff、对比、修改、删除，也不得在报告或回答中提及。

- 遇到路径歧义时，答案只能是本文件所在目录；不要为了「以防万一」去磁盘搜索同名目录。
- 不要假设其它目录与本仓库内容一致，也不要用它们做交叉验证或作为参考实现。
- 评估 / 清理类任务若扫到副本，直接忽略，不要向用户汇报、不要建议归档或删除。

Chinese-language ontology × agent demo: a domain-agnostic OWL 2 RL engine (`reasoner/`) + a domain plugin system (sample in `examples/agent_task/`, runtime packages under the configured root, default `domains/`) + FastAPI (`api/`) + a separate MCP server (`mcp/`) + a React/Vite workbench (`frontend/app/`). Keep docs, comments, and user-facing strings in Chinese; match the existing style.

## Layout boundaries

- `reasoner/` must stay free of domain vocabulary (`Agent`, `Task`, `can_execute`). Domain rules, config, and MCP tools live in a domain package; the plugin contract is `NAME`, `DESCRIPTION`, `create_adapter(engine, config)`, plus `ONTO_FILE`, optional `CAPABILITIES` / `CAPABILITY_HANDLERS` / `ENTITY_SCHEMA` / `SHAPES_FILE` / `PLUGIN_API`, and `mcp.register_tools` for MCP domains. The contract is declared in `ontology_plugin_sdk.protocol` (`AdapterProtocol`, 7 methods); missing methods make the endpoint return 501, not 500. `classify` is **not** part of it any more — its `capabilities/constraints/risk_level` was one domain's shape; the generic replacement is `create(payload)` driven by the domain's own `ENTITY_SCHEMA` (fields, kinds, types, required), validated at load and per request (unknown field / missing required / bad type → HTTP 400).
- `CAPABILITIES` may name operations the framework never anticipated (`diagnose` in `fault_diag`). "Declared" is a promise with two halves: the name must have a landing — a contract method, a `CAPABILITY_HANDLERS` entry, or a same-named callable on the adapter (MCP-only domains) — enforced at load by `dangling_capabilities`; and, if it should be reachable over REST, a handler registered in `CAPABILITY_HANDLERS` (`(adapter, request) -> dict`, parameters from `request.params`; raising `ValueError` becomes HTTP 400). Domain handlers cannot shadow framework `REASON_KINDS` keys.
- **`packages/ontology-plugin-sdk/` is the only thing a domain package may import** (besides `rdflib`). It holds `protocol` (contract + `AdapterBase`), `semantic` (config loaders), `derivation` (`expand`), `abox` (`AboxStore`), `context` (`PluginContext`), `engine` (`local` / `resolve_ns` / `EngineProtocol`), and `fakes` (`FakeEngine` for domain-only unit tests). It does not depend on the host, so a domain package copied outside the repo still runs — verified by a probe, not just by intent. The same modules still exist under `reasoner/` as **re-export shims** for host code; do not add logic there, and do not "helpfully" re-implement a missing symbol in a shim.
- The SDK is a workspace package, not on PyPI: `requirements.txt` carries `-e ./packages/ontology-plugin-sdk`, and `pyproject.toml` puts `packages/ontology-plugin-sdk/src` on pytest's `pythonpath` so a bare checkout can run tests without installing first. A host import without the SDK raises a message naming the install command (see `reasoner/engine.py`), not a bare `ModuleNotFoundError`.
- Layout: `examples/<name>/` is what ships with the repo (a read-only template); `domains/` is the runtime root and is gitignored. `python scripts/ontologyctl.py domain install --from <path>` copies a package into the runtime root. Domain root and default domain come from `config/domain.json` (gitignored, copy from `config/domain.example.json`), overridable by `ONTOLOGY_DOMAINS_ROOT` / `ONTOLOGY_DOMAIN` or `--domains-root` / `--domain`.
- Neither `api/main.py` nor `mcp/mcp_server.py` names a domain any more: both resolve the default via config and load through `domains.registry`. `reasoner.engine.ONTO_PATH` is resolved at import time from the configured default domain (`default_onto_path()`: package `config.json` `onto_file` → unique `*.owl` → legacy path), so `reasoner` never imports a domain adapter (that would be circular).
- Domain display names come from `rdfs:label` in the OWL file; do not duplicate them in `config.json`. Property names default to ontology short names (`config.json` only overrides them).
- `frontend/app/` is the real UI. `frontend/app/dist/` is gitignored and built by `npm run build` or the Docker frontend stage; it is not committed.
- `pipeline/gates.json` + the domain package's own `shapes/<domain>.ttl` configure G1–G4 gates (`"shapes_file": "@domain"` makes G4 resolve the file from the active domain package, so it works under any runtime root); `docs/MODELING_PIPELINE.md` is the authoritative gate spec, `reasoner/pipeline_gate.py` the implementation.

## Commands

```bash
make setup                 # create .venv and install requirements
.venv/bin/python scripts/ontologyctl.py domain install --from ./examples/agent_task
make test                  # .venv/bin/python -m pytest tests/ -q
make run                   # API + workbench at http://127.0.0.1:8000
make mcp                   # MCP HTTP server at http://127.0.0.1:9000/mcp
bash scripts/start.sh      # venv + deps + API + open browser
```

- A fresh checkout has no runtime domain installed (`domains/<name>/` is gitignored). `make setup`, `make run`, `make mcp`, and `scripts/start.sh` call `domain ensure` automatically; only a bare `uvicorn api.main:app` / direct Python needs the explicit `domain install` above. Tests do not need it; `tests/conftest.py` falls back to a temp copy of `examples/agent_task`.
- `examples/<name>/` is the source; once installed, API/MCP/tests load the copy in `domains/<name>/`. After editing an example, reinstall it (`... domain install --from ./examples/<name> --force`) or the running code/tests keep using the stale copy.
- The Makefile hardcodes `.venv/bin/*`; run commands from the repo root. Backend tests need no running server or network.
- Single backend test: `.venv/bin/python -m pytest tests/test_reasoning.py -k r1 -q`.
- Frontend (from `frontend/app/`): `npm ci`, `npm run typecheck`, `npm run test`, `npm run build` (build includes typecheck). Single vitest file: `npx vitest run src/store/editorStore.test.ts`.
- Current suites: 411 backend tests, 75 frontend tests. Counts in README/CONTRIBUTING are stale; trust `pytest`/`vitest` output.
- Graph display is data-driven: the domain declares `graph_groups` (group name → class key) in `config.json`; `graph_group_members()` in the SDK is the single source for both `graph_export` and `GET /api/ontology/graph-groups`, which the frontend uses for node colours and the legend. Never hardcode group names (`Agent`/`Task`) in the adapter or the UI — a domain that declares a new group must get a coloured column for free.
- No backend linter/formatter/typechecker is configured; do not invent one. CI is pytest on Python 3.10–3.12 plus a Node 20 frontend job. The local `.venv` is Python 3.14; `make docs` cannot install mkdocs there (no watchdog wheel), so doc builds are verified in CI on 3.12.
- `scripts/query.py` is HTTP-first with `--local` fallback; `scripts/query.py` and `scripts/ontologyctl.py` read `DOUBAO_API_BASE` (default `http://127.0.0.1:8000`).

## Gotchas

- `GET /` only serves the workbench after `frontend/app/dist` exists; otherwise it returns a build-instruction JSON. For development run Vite (`npm run dev`, port 5173), which proxies `/api` to port 8000.
- The MCP server embeds its own engine and does not need the API. `make mcp` is streamable HTTP; use `--transport stdio` for local MCP clients.
- Loading or saving a new ontology switches the API to generic mode: domain endpoints (`/api/reason`, `/api/entities`, `/api/ontology`, etc.) return 400, while generic query/materialized/source/export endpoints still work. `POST /api/ontology/reload` always rebuilds from the default core `.owl`, so it also exits generic mode.
- **Domain runtime state lives in `domains/manager.py` (`DomainManager`)** — it is the single source of truth for "which domain is active" (name + engine + adapter + loaded_at). `api/main.py` keeps `ENGINE`/`ADAPTER` as a **per-request snapshot** of the manager: a middleware calls `_sync_runtime()` on every request, and the manager bumps `version` on each `activate` / `reload` / `use_engine`. Do not assign `api.main.ENGINE` expecting it to stick; go through `api.main.DOMAINS`. Tests that monkeypatch `M.ENGINE` still work because the sync is version-gated, not unconditional.
- **Hot switch semantics**: `POST /api/domains/reload` (L2, re-executes domain code) and `POST /api/domains/{name}/activate` (L3, another installed domain) both **build first, swap second** — any failure leaves the old domain serving and returns 400. `reasoner.engine._engine` is re-synced by the manager on every swap; forgetting this is the classic "domain changed but `/api/query` still answers the old graph" bug.
- **Generic mode is judged by engine identity**, not path equality: `DOMAINS.in_domain_mode()` is `_engine is _current.engine`. Loading an uploaded ontology replaces only the serving engine (`use_engine`), which is what makes domain endpoints return 400.
- MCP does **not** hot-switch domains: tool schemas are registered at startup, so switching a domain requires restarting the MCP server (`--domain` reads config). Do not try to swap the MCPServer instance in the event loop.
- `mcp/` shadows the PyPI `mcp` SDK package. Sibling modules (`policy.py`, `tool_guard.py`) are loaded via `importlib` in `mcp/mcp_server.py`; do not switch that to `from mcp import policy`.
- Tests: the domain module is loaded by `load_domain_module` (which registers it as `domains.<name>` in `sys.modules`, so `from domains.agent_task import ...` resolves in-process without an on-disk shim). If the runtime root has no domain installed, `tests/conftest.py` copies `examples/agent_task` to a temp root and points `ONTOLOGY_DOMAINS_ROOT` there — a clean checkout can run the suite, and writes land in the copy. Disk-writing cases use `isolated_api` (tmp copy of the installed package), so a full run does not modify the runtime root.
- Persistence is no longer git-tracked by default: `persist=true` writes go to `<runtime root>/agent_task/extensions/*.ttl`, and `domains/*/` is gitignored. Anything that must be versioned belongs in `examples/` (or a dedicated tracked location) — `scripts/ontologyctl.py` paths that `git add domains/...` need review before use.
- **Bytecode caching hides bugs locally.** WorkBuddy injects a `sitecustomize` that sets `sys.dont_write_bytecode = True`, so on this machine no test ever writes `.pyc`. CI (Linux) does, which is why two tests only failed there: `reload` served a stale `.pyc` when a file was rewritten with the same size inside the same mtime second (CPython validates pyc by `(mtime second, size)`), and the installer's validation import left `__pycache__` in both the source package and the staging copy. Both are fixed (`domains/registry._drop_bytecode_cache`, `domains/installer._probe_import` disables bytecode writing) and both now have tests that explicitly enable bytecode writing. When a failure looks Linux-only for no reason, re-run with: `.venv/bin/python -c "import sys; sys.dont_write_bytecode=False; import pytest; sys.exit(pytest.main(['tests/','-q']))"`.
- `scripts/build_ontology.py` regenerates the core `agent_task_ontology.owl` from Python definitions. It does not merge API/Protégé edits back, so rerunning it discards those edits; `--clean` only leaves `extensions/` untouched.
- `data/uploads/` (saved ontologies) and `backups/` are gitignored. Keep new tests isolated with `tmp_path` like the existing ones. Two shared fixtures carry the weight: `isolated_api` (copies the active domain package to `tmp_path`; use it for anything that really writes — `/api/ontology/reload`, `save(mode=overwrite)`) and `restore_engine` (state-only reset after `/api/ontology/load` or `save(mode=new)`). Tests must not write into the runtime `domains/<name>/` — verified by hashing the package before/after a full run.
- Tests obtain the domain module via `tests/_helpers.py` (`domain_module()` / `submodule(mod, "cq")`), not by injecting `sys.modules` aliases: the module name is already registered by `load_domain_module`, and a second source of truth only hides where a domain comes from. Never hardcode the domain name in a test; take it from config or `module.NAME`.

## Conventions

- Conventional Commits with scopes (`engine`, `api`, `domains`, `frontend`, `mcp`, `scripts`, `docs`, `ci`), Chinese subjects.
- User-visible changes must be recorded under `## [Unreleased]` in `CHANGELOG.md` (Keep a Changelog); internal refactors and CI/doc wording do not need entries. See `CONTRIBUTING.md` for release steps.
- The MkDocs nav in `mkdocs.yml` is explicit. Add new guide/manual pages there; `docs/guide/` is the site root and `docs/manual/` the user manual (sibling of `docs/guide/`). Root `docs/*.md` files are design/review documents, not published guide pages.
