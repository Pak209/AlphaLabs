"""Phase 0 import-boundary contracts — the intended architecture, executable.

Encodes the dependency rules from docs/ARCHITECTURE.md §3-§4 as tests over the
actual import graph (parsed with ast; nothing is imported or executed). Every
contract is seeded from the graph as measured on 2026-07-04, so this suite
passes today and is allowed to TIGHTEN only:

- Fixing a violation? Delete its allowlist/debt entry in the same change.
- Adding a new cross-boundary import? That is an architecture decision — it
  needs a deliberate edit here plus a handoff entry, not a quiet append.

These tests never fail because code *moved*; they fail because a dependency
crossed a boundary in the wrong direction.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ("alpha_lab", "paper_trader", "research")


def _module_name(path: Path) -> str:
    parts = path.relative_to(REPO_ROOT).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_relative(module: str, is_package: bool, level: int, target: str | None) -> str:
    base = module.split(".") if is_package else module.split(".")[:-1]
    if level > 1:
        base = base[: len(base) - (level - 1)]
    prefix = ".".join(base)
    return f"{prefix}.{target}" if target else prefix


def build_import_graph() -> dict[str, set[str]]:
    """module name -> set of imported module names (absolute, resolved)."""
    graph: dict[str, set[str]] = {}
    for package in PACKAGES:
        for path in sorted((REPO_ROOT / package).rglob("*.py")):
            module = _module_name(path)
            is_package = path.name == "__init__.py"
            imports: set[str] = set()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        imports.add(_resolve_relative(module, is_package, node.level, node.module))
                    elif node.module:
                        imports.add(node.module)
            graph[module] = imports
    return graph


GRAPH = build_import_graph()


def _imports_from(module: str, prefix: str) -> set[str]:
    return {dep for dep in GRAPH.get(module, set())
            if dep == prefix or dep.startswith(prefix + ".")}


def _is_test_module(module: str) -> bool:
    return ".tests." in module or module.endswith(".tests")


def _violations(rule) -> list[str]:
    out = []
    for module in sorted(GRAPH):
        problem = rule(module)
        if problem:
            out.append(f"  {module}: {problem}")
    return out


# ── C1: paper_trader is a leaf package (ARCHITECTURE §4 rule 5) ─────────────
# alpha_lab -> paper_trader is the allowed direction. The reverse would create
# a cycle across the execution boundary.

def test_paper_trader_never_imports_alpha_lab_or_research():
    def rule(module: str):
        if not module.startswith("paper_trader"):
            return None
        bad = _imports_from(module, "alpha_lab") | _imports_from(module, "research")
        return f"imports {sorted(bad)}" if bad else None

    problems = _violations(rule)
    assert not problems, (
        "paper_trader must stay independent of alpha_lab and research "
        "(docs/ARCHITECTURE.md §4 rule 5):\n" + "\n".join(problems))


# ── C2: runtime never imports research (ARCHITECTURE §4 rule 4) ─────────────

def test_runtime_never_imports_research():
    def rule(module: str):
        if module.startswith("research"):
            return None
        bad = _imports_from(module, "research")
        return f"imports {sorted(bad)}" if bad else None

    problems = _violations(rule)
    assert not problems, (
        "runtime code must never import the research package "
        "(docs/ARCHITECTURE.md §4 rule 4 — isolation is absolute):\n"
        + "\n".join(problems))


# ── C3: research touches runtime only through the store read path ───────────
# Allowed: alpha_lab.database (read-only connections + schema for fixtures).
# Everything else — service, scheduler, api, paper_trader — is off-limits.

RESEARCH_RUNTIME_ALLOWLIST = {"alpha_lab.database"}


def test_research_imports_runtime_only_via_store():
    def rule(module: str):
        if not module.startswith("research"):
            return None
        runtime = _imports_from(module, "alpha_lab") | _imports_from(module, "paper_trader")
        bad = runtime - RESEARCH_RUNTIME_ALLOWLIST
        return f"imports {sorted(bad)}" if bad else None

    problems = _violations(rule)
    assert not problems, (
        "research may reach runtime only through the store read path "
        f"({sorted(RESEARCH_RUNTIME_ALLOWLIST)}); shared logic belongs in the "
        "future quant core (docs/ARCHITECTURE.md §6 Phase 1):\n" + "\n".join(problems))


# ── C4: pure-core candidates stay pure (ARCHITECTURE §4 rule 2) ─────────────
# These modules are the seed of the Phase 1 quant core / contracts layer.
# They must not grow imports of effectful modules — network, DB, frameworks,
# or the effectful internal modules listed below.
# Note: paper_trader.decision_engine importing paper_trader.audit_log (an
# interface-typed parameter; append-only local file) is today's accepted state
# and audit_log is deliberately NOT in the banned set.

PURE_CORE_MODULES = (
    "alpha_lab.scoring_engine",
    "alpha_lab.scoring_models",
    "alpha_lab.models",
    "paper_trader.models",
    "paper_trader.decision_engine",
    "research.metrics",
)
BANNED_IN_PURE_CORE = (
    "sqlite3", "socket", "subprocess", "http", "urllib", "httpx", "requests",
    "fastapi", "uvicorn", "apscheduler", "pywebpush",
    "alpha_lab.database", "alpha_lab.repository", "alpha_lab.live_sources",
    "alpha_lab.market_data", "alpha_lab.notifications", "alpha_lab.service",
    "paper_trader.alpaca_client", "paper_trader.simulated_broker",
    "paper_trader.config",
)


def test_pure_core_modules_have_no_effectful_imports():
    problems = []
    for module in PURE_CORE_MODULES:
        assert module in GRAPH, f"pure-core module {module} disappeared"
        bad = set()
        for banned in BANNED_IN_PURE_CORE:
            bad |= _imports_from(module, banned)
        if bad:
            problems.append(f"  {module}: imports {sorted(bad)}")
    assert not problems, (
        "pure-core candidates must stay free of effectful imports "
        "(docs/ARCHITECTURE.md §4 rule 2 — a single effectful import in the "
        "quant core is a build failure):\n" + "\n".join(problems))


# ── C5: the store foundation imports nothing internal ───────────────────────

def test_database_module_is_a_foundation():
    internal = set()
    for package in PACKAGES:
        internal |= _imports_from("alpha_lab.database", package)
    assert not internal, (
        f"alpha_lab.database must not import other project modules, found "
        f"{sorted(internal)} (docs/ARCHITECTURE.md §3 store boundary)")


# ── C6: delivery entry points are not imported from below ───────────────────
# alpha_lab.api and alpha_lab.mcp_server are transport surfaces; only the
# process entry point (main) and tests may import them.

DELIVERY_ENTRYPOINTS = ("alpha_lab.api", "alpha_lab.mcp_server")
ALLOWED_DELIVERY_IMPORTERS = {"alpha_lab.main"}


def test_delivery_entrypoints_only_imported_by_main_and_tests():
    problems = []
    for target in DELIVERY_ENTRYPOINTS:
        for module in sorted(GRAPH):
            if module == target or _is_test_module(module):
                continue
            if _imports_from(module, target) and module not in ALLOWED_DELIVERY_IMPORTERS:
                problems.append(f"  {module} imports {target}")
    assert not problems, (
        "delivery entry points must not be imported by lower layers "
        "(docs/ARCHITECTURE.md §3 delivery boundary):\n" + "\n".join(problems))


# ── C7: the alpha_lab -> paper_trader bridge set is frozen ──────────────────
# Exactly these non-test modules cross the package boundary today. A new
# bridge is an architecture decision (it widens the seam Phase 2/3 must cut),
# so it requires a deliberate entry here.

ALLOWED_PAPER_TRADER_BRIDGES = {
    "alpha_lab.service",          # orchestration: decision path + trade path
    "alpha_lab.scheduler",        # orchestration: inbox processing job
    "alpha_lab.options_selector", # execution adapter use: contract quotes
    "alpha_lab.portfolio",        # reads RiskConfig for exposure context
}


def test_cross_package_bridges_are_frozen():
    problems = []
    for module in sorted(GRAPH):
        if not module.startswith("alpha_lab") or _is_test_module(module):
            continue
        if _imports_from(module, "paper_trader") and module not in ALLOWED_PAPER_TRADER_BRIDGES:
            problems.append(f"  {module} imports paper_trader")
    assert not problems, (
        "new alpha_lab -> paper_trader bridge modules require a deliberate "
        "contract update (docs/ARCHITECTURE.md §4 rule 5):\n" + "\n".join(problems))


# ── C8: known layer debt register (kept accurate in both directions) ────────
# Violations of the *target* architecture that exist today and are scheduled
# for later phases. Each entry must still exist — when a phase removes one,
# delete it here in the same change so the register never lies.

KNOWN_LAYER_DEBT = {
    # service (orchestration) imports review_api (delivery builders);
    # scheduled to move in Phase 2 (use-case decomposition).
    ("alpha_lab.service", "alpha_lab.review_api"),
    # service (orchestration) imports notifications (delivery);
    # scheduled for the same decomposition.
    ("alpha_lab.service", "alpha_lab.notifications"),
}


def test_known_layer_debt_register_is_accurate():
    stale = []
    for importer, imported in sorted(KNOWN_LAYER_DEBT):
        if not _imports_from(importer, imported):
            stale.append(f"  {importer} no longer imports {imported} — "
                         "remove the entry from KNOWN_LAYER_DEBT")
    assert not stale, (
        "debt register out of date (a cleanup landed — record it):\n"
        + "\n".join(stale))
