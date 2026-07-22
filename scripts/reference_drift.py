#!/usr/bin/env python
"""reference_drift.py - Drift detector for Agno SDK reference pages (read-only).

For every SDK reference page under reference/**/*.mdx (resolving <Snippet .../>
includes from _snippets/ and <ResponseField> blocks), determine the documented
parameter set and the class (or function/method) it documents, extract ground
truth from the agno source (runtime introspection where the module is
importable in the running venv, pure-AST fallback with inheritance resolution
otherwise), and report per page:
  - missing params        (in source, not documented)
  - phantom params        (documented, absent from source entirely)
  - documented aliases    (documented params that are deprecated aliases in
                           source: counted separately, NOT phantoms)
  - inherited documented  (documented, not in the class's own signature but
                           accepted via **kwargs from a parent: NOT phantoms)
  - wrong defaults        (table states a concrete default contradicting source)

Writes scripts/out/drift-report.json. Never modifies docs pages.

Run with a venv where agno is importable (see scripts/README.md):
  python scripts/reference_drift.py

The agno repo defaults to the ./agno symlink at the repo root; override with
the AGNO_REPO env var.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import os
import re
from dataclasses import MISSING as DC_MISSING
from dataclasses import fields as dc_fields
from dataclasses import is_dataclass
from datetime import datetime, timezone
from pathlib import Path

DOCS_ROOT = Path(__file__).resolve().parents[1]
AGNO_ROOT = Path(os.environ.get("AGNO_REPO") or DOCS_ROOT / "agno")
AGNO_SRC = AGNO_ROOT / "libs/agno/agno"
OUT_PATH = Path(__file__).resolve().parent / "out" / "drift-report.json"

REQUIRED = "<required>"

# ---------------------------------------------------------------------------
# Page -> target overrides. "module:Class", "module:function()" or None
# (= rely on per-table heading resolution only).
# ---------------------------------------------------------------------------
PAGE_OVERRIDES: dict[str, object] = {
    "reference/agents/agent.mdx": "agno.agent.agent:Agent",
    "reference/agents/run-response.mdx": "agno.run.agent:RunOutput",
    "reference/agents/session.mdx": "agno.session.agent:AgentSession",
    "reference/agents/remote-agent.mdx": "agno.remote.agent:RemoteAgent",
    "reference/teams/team.mdx": "agno.team.team:Team",
    "reference/teams/team-response.mdx": "agno.run.team:TeamRunOutput",
    "reference/teams/session.mdx": "agno.session.team:TeamSession",
    "reference/teams/remote-team.mdx": "agno.remote.team:RemoteTeam",
    "reference/workflows/workflow.mdx": "agno.workflow.workflow:Workflow",
    "reference/workflows/step.mdx": "agno.workflow.step:Step",
    "reference/workflows/steps-step.mdx": "agno.workflow.steps:Steps",
    "reference/workflows/loop-steps.mdx": "agno.workflow.loop:Loop",
    "reference/workflows/parallel-steps.mdx": "agno.workflow.parallel:Parallel",
    "reference/workflows/conditional-steps.mdx": "agno.workflow.condition:Condition",
    "reference/workflows/router-steps.mdx": "agno.workflow.router:Router",
    "reference/workflows/run-output.mdx": "agno.run.workflow:WorkflowRunOutput",
    "reference/workflows/session.mdx": "agno.session.workflow:WorkflowSession",
    "reference/workflows/step_input.mdx": "agno.workflow.types:StepInput",
    "reference/workflows/step_output.mdx": "agno.workflow.types:StepOutput",
    "reference/workflows/remote-workflow.mdx": "agno.remote.workflow:RemoteWorkflow",
    "reference/models/model.mdx": "agno.models.base:Model",
    "reference/models/azure-open-ai.mdx": "agno.models.azure.openai_chat:AzureOpenAI",
    "reference/models/azure.mdx": "agno.models.azure.ai_foundry:AzureAIFoundry",
    "reference/models/bedrock-claude.mdx": "agno.models.aws.claude:Claude",
    "reference/models/ibm-watsonx.mdx": "agno.models.ibm.watsonx:WatsonX",
    "reference/models/meta.mdx": "agno.models.meta.llama:Llama",
    "reference/models/vercel.mdx": "agno.models.vercel.v0:V0",
    "reference/tracing/span.mdx": "agno.tracing.schemas:Span",
    "reference/tracing/trace.mdx": "agno.tracing.schemas:Trace",
    "reference/tools/toolkit.mdx": "agno.tools.toolkit:Toolkit",
    "reference/tools/decorator.mdx": "agno.tools.decorator:tool()",
    "reference/tools/retry-agent-run.mdx": "agno.exceptions:RetryAgentRun",
    "reference/tools/stop-agent-run.mdx": "agno.exceptions:StopAgentRun",
    "reference/storage/migrations.mdx": "agno.db.migrations.manager:MigrationManager",
    "reference/memory/memory.mdx": "agno.memory.manager:MemoryManager",
    "reference/session/summary_manager.mdx": "agno.session.summary:SessionSummaryManager",
    "reference/compression/compression-manager.mdx": "agno.compression.manager:CompressionManager",
    "reference/knowledge/knowledge.mdx": "agno.knowledge.knowledge:Knowledge",
    "reference/knowledge/chunking/csv-row.mdx": "agno.knowledge.chunking.row:RowChunking",
    "reference/knowledge/embedder/huggingface.mdx":
        "agno.knowledge.embedder.huggingface:HuggingfaceCustomEmbedder",
    "reference/agent-os/agent-os.mdx": "agno.os.app:AgentOS",
    # JWTMiddleware is an alias: `JWTMiddleware = AuthMiddleware` in jwt.py
    "reference/agent-os/jwt-middleware.mdx": "agno.os.middleware.jwt:AuthMiddleware",
    "reference/hooks/hook-decorator.mdx": "agno.hooks.decorator:hook()",
    "reference/clients/agentos-client.mdx": "agno.client.os:AgentOSClient",
    "reference/clients/a2a-client.mdx": "agno.client.a2a:A2AClient",
}

# (page, normalized table heading) -> "module:Class" for tables the generic
# resolution maps wrongly.
TABLE_OVERRIDES: dict[tuple[str, str], str] = {
    # docs "Base RunOutputEvent Attributes" documents the agent-level base
    # event (agent_id, content, ...), which is BaseAgentRunEvent in source;
    # BaseRunOutputEvent in run/base.py is a thin mixin without those fields.
    ("reference/agents/run-response.mdx", "baserunoutputevent"): "agno.run.agent:BaseAgentRunEvent",
    ("reference/teams/team-response.mdx", "baserunoutputevent"): "agno.run.team:BaseTeamRunEvent",
}

SKIP_PAGES: dict[str, str] = {
    "reference/agno-infra/cli/ws/config.mdx": "CLI command page (agno_infra `ag ws` CLI), not an SDK class",
    "reference/agno-infra/cli/ws/create.mdx": "CLI command page (agno_infra `ag ws` CLI), not an SDK class",
    "reference/agno-infra/cli/ws/delete.mdx": "CLI command page (agno_infra `ag ws` CLI), not an SDK class",
    "reference/agno-infra/cli/ws/down.mdx": "CLI command page (agno_infra `ag ws` CLI), not an SDK class",
    "reference/agno-infra/cli/ws/patch.mdx": "CLI command page (agno_infra `ag ws` CLI), not an SDK class",
    "reference/agno-infra/cli/ws/restart.mdx": "CLI command page (agno_infra `ag ws` CLI), not an SDK class",
    "reference/agno-infra/cli/ws/up.mdx": "CLI command page (agno_infra `ag ws` CLI), not an SDK class",
    "reference/hooks/pre-hooks.mdx":
        "documents framework-injected hook callable arguments, not a class signature",
    "reference/hooks/post-hooks.mdx":
        "documents framework-injected hook callable arguments, not a class signature",
    "reference/hooks/base-guardrail.mdx":
        "abstract interface page (check/async_check methods as prose bullets), no param table",
}

# Directory-specific candidate-name transforms (applied to the page title).
DIR_SUFFIX_RULES = {
    "reference/knowledge/embedder": ["{t}Embedder", "{t}"],
    "reference/knowledge/chunking": ["{t}Chunking", "{t}Chunker", "{t}"],
    "reference/knowledge/reader": ["{t}Reader", "{t}"],
    "reference/knowledge/reranker": ["{t}Reranker", "{t}"],
    "reference/models": ["{t}", "{t}Chat"],
    "reference/storage": ["{t}", "{t}Db"],
    "reference/hooks": ["{t}", "{t}Guardrail"],
}

# Preferred source-module prefixes per page directory (ordered).
DIR_MODULE_PREF = {
    "reference/storage": ["agno.db"],
    "reference/models": ["agno.models"],
    "reference/knowledge/embedder": ["agno.knowledge.embedder"],
    "reference/knowledge/reader": ["agno.knowledge.reader"],
    "reference/knowledge/chunking": ["agno.knowledge.chunking"],
    "reference/knowledge/reranker": ["agno.knowledge.reranker"],
    "reference/knowledge": ["agno.knowledge"],
    "reference/hooks": ["agno.guardrails", "agno.hooks"],
    "reference/tracing": ["agno.tracing"],
    "reference/workflows": ["agno.workflow", "agno.run.workflow"],
    "reference/teams": ["agno.team", "agno.run.team", "agno.session.team"],
    "reference/agents": ["agno.agent", "agno.run.agent", "agno.session.agent"],
    "reference/memory": ["agno.memory"],
    "reference/agent-os": ["agno.os"],
    "reference/clients": ["agno.client"],
    "reference/run": ["agno.metrics", "agno.run"],
    "reference/reasoning": ["agno.reasoning", "agno.run.agent"],
}

GENERIC_HEADINGS = {
    "", "parameters", "params", "constructor", "constructor parameters",
    "attributes", "fields", "initialization", "init parameters",
    "core parameters", "reference", "api reference",
}
HEADING_SUFFIX_WORDS = ("attributes", "parameters", "params", "fields", "class", "object")


def norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


# ---------------------------------------------------------------------------
# Source index
# ---------------------------------------------------------------------------

def build_source_index() -> dict[str, list[tuple[str, Path]]]:
    index: dict[str, list[tuple[str, Path]]] = {}
    for py in sorted(AGNO_SRC.rglob("*.py")):
        rel = py.relative_to(AGNO_SRC.parent)
        module = ".".join(rel.with_suffix("").parts)
        if module.endswith(".__init__"):
            module = module[: -len(".__init__")]
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                index.setdefault(node.name, []).append((module, py))
    return index


# ---------------------------------------------------------------------------
# Ground truth containers
# ---------------------------------------------------------------------------

class SourceParams:
    def __init__(self, params: dict[str, dict], method: str, module: str, name: str,
                 has_kwargs: bool = False, inherited: dict[str, str] | None = None,
                 properties: set[str] | None = None):
        self.params = params          # name -> {"default": str|REQUIRED, "deprecated": bool}
        self.method = method          # "introspection" | "ast"
        self.module = module
        self.name = name
        self.has_kwargs = has_kwargs
        self.inherited = inherited or {}   # parent-signature params reachable via **kwargs
        self.properties = properties or set()  # computed @property names on the class


def _default_repr(val) -> str:
    try:
        return repr(val)
    except Exception:
        return "<unrepresentable>"


def package_corpus(file_path: Path | None) -> str:
    """Source text of every .py file in the same package dir (deprecation confirm)."""
    if file_path is None:
        return ""
    out = []
    try:
        for py in file_path.parent.glob("*.py"):
            out.append(py.read_text(encoding="utf-8"))
    except OSError:
        pass
    return "\n".join(out)


def find_deprecated_params(sig_source: str, param_names: set[str], corpus: str) -> set[str]:
    """Params marked deprecated via comments in the signature/class body.

    - inline comment containing 'deprecat' on the param's line -> deprecated
    - a '# ... deprecat ...' comment line starts a block: following params are
      deprecated until one is confirmed active, i.e. the package corpus contains
      a direct assignment `<recv>.<name> = <name>` (handles both `self.x = x`
      and delegated `team.x = x` in _init.py).
    """
    deprecated: set[str] = set()
    block_active = False
    for line in sig_source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            block_active = "deprecat" in stripped.lower()
            continue
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*[:=]", stripped)
        pname = m.group(1) if m and m.group(1) in param_names else None
        inline_dep = "#" in line and "deprecat" in line.split("#", 1)[1].lower()
        if pname:
            if inline_dep:
                deprecated.add(pname)
            elif block_active:
                confirmed = re.search(
                    rf"\w+\.{re.escape(pname)}\s*=\s*{re.escape(pname)}\b", corpus
                )
                if confirmed:
                    block_active = False
                else:
                    deprecated.add(pname)
        elif stripped and not stripped.startswith(("@", ")", "'", '"')):
            block_active = False
    return deprecated


def _sig_params(sig: inspect.Signature) -> tuple[dict[str, dict], bool]:
    params: dict[str, dict] = {}
    has_kwargs = False
    for pname, p in sig.parameters.items():
        if pname in ("self", "cls") or pname.startswith("_"):
            continue
        if p.kind is inspect.Parameter.VAR_KEYWORD:
            has_kwargs = True
            continue
        if p.kind is inspect.Parameter.VAR_POSITIONAL:
            continue
        default = REQUIRED if p.default is inspect.Parameter.empty else _default_repr(p.default)
        params[pname] = {"default": default, "deprecated": False}
    return params, has_kwargs


def _mro_inherited(obj, own: set[str]) -> dict[str, str]:
    """Union of parent init params / dataclass fields not in the class's own set."""
    inherited: dict[str, str] = {}
    for klass in obj.__mro__[1:]:
        if not getattr(klass, "__module__", "").startswith("agno"):
            continue
        try:
            if is_dataclass(klass):
                for f in dc_fields(klass):
                    if f.name.startswith("_") or f.name in own:
                        continue
                    inherited.setdefault(f.name, "")
            elif "__init__" in vars(klass):
                p, _ = _sig_params(inspect.signature(klass.__init__))
                for k, v in p.items():
                    if k not in own:
                        inherited.setdefault(k, v["default"])
        except (ValueError, TypeError):
            continue
    return inherited


def _class_properties(obj) -> set[str]:
    import functools
    props: set[str] = set()
    for klass in getattr(obj, "__mro__", ()):
        if not getattr(klass, "__module__", "").startswith("agno"):
            continue
        for n, v in vars(klass).items():
            if not n.startswith("_") and isinstance(v, (property, functools.cached_property)):
                props.add(n)
    return props


def introspect_target(module_name: str, obj_name: str, is_function: bool) -> SourceParams:
    mod = importlib.import_module(module_name)
    obj = getattr(mod, obj_name)
    src_file = None
    try:
        src_file = Path(inspect.getsourcefile(obj))
    except (OSError, TypeError):
        pass
    corpus = package_corpus(src_file)

    if is_function:
        params, has_kwargs = _sig_params(inspect.signature(obj))
        if not params and has_kwargs:
            raise ValueError("runtime signature is (*args, **kwargs); AST needed for overloads")
        try:
            src = inspect.getsource(obj)
        except OSError:
            src = ""
        for p in find_deprecated_params(src, set(params), corpus):
            params[p]["deprecated"] = True
        return SourceParams(params, "introspection", module_name, obj_name, has_kwargs)

    # pydantic v2 models
    if hasattr(obj, "model_fields") and isinstance(getattr(obj, "model_fields", None), dict):
        params: dict[str, dict] = {}
        for fname, finfo in obj.model_fields.items():
            if fname.startswith("_"):
                continue
            try:
                if finfo.is_required():
                    default = REQUIRED
                elif finfo.default_factory is not None:
                    default = _default_repr(finfo.default_factory())
                else:
                    default = _default_repr(finfo.default)
            except Exception:
                default = "<factory>"
            params[fname] = {"default": default, "deprecated": False}
        return SourceParams(params, "introspection", module_name, obj_name,
                            properties=_class_properties(obj))

    if is_dataclass(obj) and "__init__" not in vars(obj):
        # synthesized dataclass __init__: fields include inherited ones
        src = ""
        for klass in reversed(obj.__mro__):
            if is_dataclass(klass) and klass.__module__.startswith("agno"):
                try:
                    src += inspect.getsource(klass) + "\n"
                except OSError:
                    pass
        params = {}
        for f in dc_fields(obj):
            if f.name.startswith("_"):
                continue
            if f.default is not DC_MISSING:
                default = _default_repr(f.default)
            elif f.default_factory is not DC_MISSING:  # type: ignore[misc]
                try:
                    default = _default_repr(f.default_factory())
                except Exception:
                    default = "<factory>"
            else:
                default = REQUIRED
            params[f.name] = {"default": default, "deprecated": False}
        for p in find_deprecated_params(src, set(params), corpus):
            params[p]["deprecated"] = True
        return SourceParams(params, "introspection", module_name, obj_name,
                            properties=_class_properties(obj))

    sig = inspect.signature(obj.__init__)
    params, has_kwargs = _sig_params(sig)
    try:
        src = inspect.getsource(obj.__init__)
    except (OSError, TypeError):
        src = ""
    for p in find_deprecated_params(src, set(params), corpus):
        params[p]["deprecated"] = True
    inherited = _mro_inherited(obj, set(params)) if has_kwargs else {}
    return SourceParams(params, "introspection", module_name, obj_name, has_kwargs,
                        inherited, _class_properties(obj))


class AstExtractor:
    """Pure-AST fallback with inheritance resolution inside the agno tree."""

    def __init__(self, index: dict[str, list[tuple[str, Path]]]):
        self.index = index
        self._tree_cache: dict[Path, ast.Module] = {}
        self._src_cache: dict[Path, str] = {}

    def _load(self, path: Path) -> tuple[ast.Module, str]:
        if path not in self._tree_cache:
            text = path.read_text(encoding="utf-8")
            self._src_cache[path] = text
            self._tree_cache[path] = ast.parse(text)
        return self._tree_cache[path], self._src_cache[path]

    def find_class(self, name: str, module_hint: str | None = None):
        entries = self.index.get(name) or []
        if module_hint:
            entries = [e for e in entries if e[0] == module_hint] or entries
        for module, path in entries:
            tree, _ = self._load(path)
            for node in tree.body:
                if isinstance(node, ast.ClassDef) and node.name == name:
                    return node, path, module
        return None

    def _resolve_import(self, path: Path, local_name: str) -> tuple[str, str] | None:
        """Map a name used in `path` back to (real_name, module) via its imports."""
        tree, _ = self._load(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    if (alias.asname or alias.name) == local_name:
                        return alias.name, node.module
        return None

    def _mro_chain(self, name: str, module_hint: str | None):
        chain = []
        seen: set[tuple[str, str]] = set()

        def visit(cname: str, hint: str | None):
            found = self.find_class(cname, hint)
            if not found:
                return
            node, path, module = found
            if (cname, module) in seen:
                return
            seen.add((cname, module))
            chain.append((node, path, module))
            for base in node.bases:
                base_name = None
                if isinstance(base, ast.Name):
                    base_name = base.id
                elif isinstance(base, ast.Attribute):
                    base_name = base.attr
                if not base_name or base_name in ("ABC", "object", "Enum", "str", "Exception"):
                    continue
                resolved = self._resolve_import(path, base_name)
                if resolved:
                    visit(resolved[0], resolved[1])
                else:
                    visit(base_name, None)

        visit(name, module_hint)
        return chain

    @staticmethod
    def _fn_params(fn: ast.FunctionDef) -> tuple[dict[str, dict], bool]:
        params: dict[str, dict] = {}
        args = fn.args
        pos = args.posonlyargs + args.args
        defaults = [None] * (len(pos) - len(args.defaults)) + list(args.defaults)
        for a, d in zip(pos, defaults):
            if a.arg in ("self", "cls") or a.arg.startswith("_"):
                continue
            params[a.arg] = {"default": ast.unparse(d) if d is not None else REQUIRED,
                             "deprecated": False}
        for a, d in zip(args.kwonlyargs, args.kw_defaults):
            if a.arg.startswith("_"):
                continue
            params[a.arg] = {"default": ast.unparse(d) if d is not None else REQUIRED,
                             "deprecated": False}
        return params, args.kwarg is not None

    def extract(self, name: str, module_hint: str | None = None) -> SourceParams | None:
        mro = self._mro_chain(name, module_hint)
        if not mro:
            return None
        _node, path, module = mro[0]
        corpus = package_corpus(path)

        init_owner = None
        for cnode, cpath, _cmod in mro:
            for item in cnode.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    init_owner = (item, cpath, cnode)
                    break
            if init_owner:
                break

        params: dict[str, dict] = {}
        inherited: dict[str, str] = {}
        has_kwargs = False
        properties: set[str] = set()
        for cnode, _cp, _cm in mro:
            for item in cnode.body:
                if isinstance(item, ast.FunctionDef) and not item.name.startswith('_'):
                    for dec in item.decorator_list:
                        dn = dec.id if isinstance(dec, ast.Name) else (
                            dec.attr if isinstance(dec, ast.Attribute) else '')
                        if dn in ('property', 'cached_property'):
                            properties.add(item.name)
        if init_owner:
            fn, fpath, owner_node = init_owner
            _, ftext = self._load(fpath)
            params, has_kwargs = self._fn_params(fn)
            fn_src = ast.get_source_segment(ftext, fn) or ""
            for p in find_deprecated_params(fn_src, set(params), package_corpus(fpath)):
                params[p]["deprecated"] = True
            if has_kwargs:
                # union of ancestor __init__ params and dataclass fields
                for cnode, cpath, _cmod in mro:
                    if cnode is owner_node:
                        continue
                    for item in cnode.body:
                        if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                            p2, _ = self._fn_params(item)
                            for k, v in p2.items():
                                if k not in params:
                                    inherited.setdefault(k, v["default"])
                        elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                            k = item.target.id
                            if not k.startswith("_") and k not in params:
                                if "ClassVar" not in ast.unparse(item.annotation):
                                    inherited.setdefault(k, "")
        else:
            combined_src = ""
            for cnode, cpath, _cmod in reversed(mro):
                _, ctext = self._load(cpath)
                combined_src += (ast.get_source_segment(ctext, cnode) or "") + "\n"
                for item in cnode.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        fname = item.target.id
                        if fname.startswith("_"):
                            continue
                        if "ClassVar" in ast.unparse(item.annotation):
                            continue
                        if item.value is not None:
                            dv = ast.unparse(item.value)
                            m = re.match(r"field\(default_factory=(\w+)\)", dv)
                            if m:
                                dv = {"list": "[]", "dict": "{}", "set": "set()"}.get(m.group(1), dv)
                            m2 = re.match(r"field\(default=(.+)\)$", dv)
                            if m2:
                                dv = m2.group(1)
                        else:
                            dv = REQUIRED
                        params[fname] = {"default": dv, "deprecated": False}
            for p in find_deprecated_params(combined_src, set(params), corpus):
                params[p]["deprecated"] = True
        return SourceParams(params, "ast", module, name, has_kwargs, inherited, properties)

    def extract_function(self, module_hint: str | None, name: str) -> SourceParams | None:
        entries = self.index.get(name) or []
        if module_hint:
            entries = [e for e in entries if e[0] == module_hint] or entries
        best: tuple[int, ast.FunctionDef, str, str] | None = None
        for module, path in entries:
            tree, text = self._load(path)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                    p, _ = self._fn_params(node)
                    if best is None or len(p) > best[0]:
                        best = (len(p), node, module, text)
        if best is None:
            return None
        _n, node, module, text = best
        params, has_kwargs = self._fn_params(node)
        fn_src = ast.get_source_segment(text, node) or ""
        for p in find_deprecated_params(fn_src, set(params), fn_src):
            params[p]["deprecated"] = True
        return SourceParams(params, "ast", module, name, has_kwargs)


# ---------------------------------------------------------------------------
# Docs-side parsing
# ---------------------------------------------------------------------------

SNIPPET_RE = re.compile(r"<Snippet\s+file=\"([^\"]+)\"\s*/?>")
NAME_COL_HEADERS = {"parameter", "attribute", "field", "name", "argument", "property"}
RESPONSE_FIELD_RE = re.compile(
    r"<ResponseField\s+name=\"([^\"]+)\"([^>]*)>", re.DOTALL
)


def resolve_snippets(text: str, depth: int = 0) -> tuple[str, list[str]]:
    used: list[str] = []
    if depth > 3:
        return text, used

    def repl(m: re.Match) -> str:
        fname = m.group(1)
        path = DOCS_ROOT / "_snippets" / fname
        if not path.exists():
            return f"\n<!-- missing snippet {fname} -->\n"
        used.append(fname)
        inner, inner_used = resolve_snippets(path.read_text(encoding="utf-8"), depth + 1)
        used.extend(inner_used)
        return "\n" + inner + "\n"

    return SNIPPET_RE.sub(repl, text), used


def parse_frontmatter(text: str) -> dict[str, str]:
    fm: dict[str, str] = {}
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            kv = re.match(r"(\w+):\s*(.+)", line.strip())
            if kv:
                fm[kv.group(1)] = kv.group(2).strip().strip("\"'")
    return fm


def split_row(line: str) -> list[str]:
    parts = re.split(r"(?<!\\)\|", line.strip())
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [p.strip() for p in parts]


def extract_tables(text: str) -> list[dict]:
    """Param tables and ResponseField groups: [{heading, rows:[{name,type,default}]}]."""
    tables: list[dict] = []
    heading = ""
    last_by_level: dict[int, str] = {}
    cur_level = 0
    lines = text.splitlines()
    i = 0
    in_code = False
    rf_group: list[dict] | None = None
    rf_heading = ""
    rf_chain: list[str] = []

    def chain() -> list[str]:
        """Ancestor headings above the current one, nearest first."""
        return [last_by_level[lv] for lv in sorted(last_by_level, reverse=True)
                if lv < cur_level and last_by_level[lv]]

    def flush_rf():
        nonlocal rf_group
        if rf_group:
            tables.append({"heading": rf_heading, "chain": rf_chain,
                           "header": ["parameter", "type", "default"],
                           "raw_rows": None, "rows": rf_group, "kind": "responsefield"})
        rf_group = None

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            in_code = not in_code
            i += 1
            continue
        if in_code:
            i += 1
            continue
        hm = re.match(r"(#{2,4})\s+(.*)", line.strip())
        if hm:
            flush_rf()
            heading = hm.group(2).strip().strip("`")
            cur_level = len(hm.group(1))
            last_by_level[cur_level] = heading
            for lv in list(last_by_level):
                if lv > cur_level:
                    del last_by_level[lv]
            i += 1
            continue
        rfm = RESPONSE_FIELD_RE.search(line)
        if rfm:
            name = rfm.group(1)
            attrs = rfm.group(2)
            tm = re.search(r"type=\"([^\"]+)\"", attrs)
            dm = re.search(r"default=\"([^\"]+)\"", attrs)
            default = dm.group(1) if dm else ("Required" if "required" in attrs else None)
            if rf_group is None:
                rf_group = []
                rf_heading = heading
                rf_chain = chain()
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
                rf_group.append({"name": name, "type": tm.group(1) if tm else "",
                                 "default": default})
            i += 1
            continue
        if line.strip().startswith("|") and i + 1 < len(lines) and re.match(
            r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]
        ) and "-" in lines[i + 1]:
            header = [h.lower().strip().strip("*") for h in split_row(line)]
            raw_rows = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                cells = split_row(lines[j])
                if cells:
                    raw_rows.append(cells)
                j += 1
            tables.append({"heading": heading, "chain": chain(), "header": header,
                           "raw_rows": raw_rows, "kind": "table"})
            i = j
            continue
        i += 1
    flush_rf()

    out = []
    for t in tables:
        if t["kind"] == "responsefield":
            if t["rows"]:
                out.append({"heading": t["heading"], "chain": t["chain"], "rows": t["rows"]})
            continue
        header = t["header"]
        if not header:
            continue
        first = re.sub(r"[^a-z]", "", header[0])
        if first not in NAME_COL_HEADERS:
            continue
        type_idx = next((k for k, h in enumerate(header) if h.strip() == "type"), None)
        if type_idx is None:
            continue
        default_idx = next((k for k, h in enumerate(header) if "default" in h), None)
        rows = []
        for cells in t["raw_rows"]:
            if not cells:
                continue
            raw_name = cells[0]
            m = re.search(r"`([^`]+)`", raw_name)
            name = m.group(1) if m else raw_name.strip()
            name = re.sub(r"\s*\(.*\)$", "", name.strip().strip("*"))
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
                continue
            default = cells[default_idx] if default_idx is not None and default_idx < len(cells) else None
            rows.append({"name": name, "default": default,
                         "type": cells[type_idx] if type_idx < len(cells) else ""})
        if rows:
            out.append({"heading": t["heading"], "chain": t["chain"], "rows": rows})
    return out


# ---------------------------------------------------------------------------
# Default normalization
# ---------------------------------------------------------------------------

def norm_default(val: str | None) -> str | None:
    if val is None:
        return None
    v = val.strip().strip("`").strip()
    if v in ("", "-", "—", "N/A", "n/a"):
        return None
    if v.lower() in ("required", "(required)"):
        return REQUIRED
    v = v.strip("\"'")
    low = v.lower()
    if low in ("none", "null"):
        return "none"
    if low in ("true", "false"):
        return low
    if v.endswith(".value") or re.match(r"^\w+(\.\w+){2,}$", v):
        return None  # symbolic reference like WorkflowRunEvent.workflow_started.value
    em = re.match(r"<?(\w+)\.(\w+)(?::.*)?>?$", v)
    if em and not re.match(r"^-?\d+(\.\d+)?$", v):
        return f"{em.group(1)}.{em.group(2)}".lower()
    try:
        return repr(float(v))
    except ValueError:
        pass
    return low


def comparable(nv: str | None) -> bool:
    if nv is None:
        return False
    if nv == REQUIRED:
        return True
    if any(tok in nv for tok in ("(", "lambda", "factory", "object at", "<")):
        return False
    if " " in nv:  # prose defaults like "JWT_VERIFICATION_KEY env var"
        return False
    return True


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

class Resolver:
    def __init__(self, index: dict[str, list[tuple[str, Path]]], extractor: AstExtractor):
        self.index = index
        self.extractor = extractor
        self.norm_index: dict[str, list[str]] = {}
        for cname in index:
            self.norm_index.setdefault(norm_key(cname), []).append(cname)
        self.cache: dict[tuple, SourceParams | None] = {}

    def order_entries(self, name: str, module_hint: str | None, prefs: list[str]):
        entries = list(self.index.get(name) or [])

        def rank(e):
            module = e[0]
            if module_hint and module == module_hint:
                return (0, 0)
            for k, p in enumerate(prefs):
                if module == p or module.startswith(p + "."):
                    return (1, k)
            return (2, 0)

        entries.sort(key=rank)
        return entries

    def get_params(self, name: str, module_hint: str | None = None,
                   is_function: bool = False, prefs: list[str] | None = None) -> SourceParams | None:
        prefs = prefs or []
        key = (name, module_hint, is_function, tuple(prefs))
        if key in self.cache:
            return self.cache[key]
        result: SourceParams | None = None
        entries = self.order_entries(name, module_hint, prefs)
        for module, _path in entries[:4]:
            try:
                result = introspect_target(module, name, is_function)
                break
            except BaseException:
                continue
        if result is None:
            best_module = entries[0][0] if entries else module_hint
            if is_function:
                result = self.extractor.extract_function(best_module, name)
            else:
                result = self.extractor.extract(name, best_module)
        self.cache[key] = result
        return result

    def get_method_params(self, module_hint: str | None, class_name: str,
                          method: str, prefs: list[str]) -> SourceParams | None:
        entries = self.order_entries(class_name, module_hint, prefs)
        for module, _path in entries[:4]:
            try:
                mod = importlib.import_module(module)
                cls = getattr(mod, class_name)
                fn = getattr(cls, method, None)
                if fn is None:
                    continue
                params, has_kwargs = _sig_params(inspect.signature(fn))
                return SourceParams(params, "introspection", module,
                                    f"{class_name}.{method}", has_kwargs)
            except BaseException:
                continue
        return None

    def candidates_for(self, title: str, rel_dir: str, stem: str) -> list[str]:
        titles = [title, title.replace(" ", ""), title.replace("-", ""),
                  title.replace(" ", "").replace("-", "")]
        titles.append("".join(w.capitalize() for w in re.split(r"[-_]", stem)))
        cands: list[str] = []
        rules = None
        for d, r in DIR_SUFFIX_RULES.items():
            if rel_dir.startswith(d):
                rules = r
                break
        for t in titles:
            if not t:
                continue
            if rules:
                for pattern in rules:
                    cands.append(pattern.format(t=t))
            cands.append(t)
        seen, out = set(), []
        for c in cands:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out

    def resolve_name(self, candidate: str) -> str | None:
        if not candidate:
            return None
        if candidate in self.index:
            return candidate
        hits = self.norm_index.get(norm_key(candidate))
        return hits[0] if hits else None


IMPORT_RE = re.compile(r"from\s+(agno[\w.]*)\s+import\s+([\w, ]+)")


def imports_in_page(text: str) -> list[tuple[str, str]]:
    out = []
    for m in IMPORT_RE.finditer(text):
        for name in m.group(2).split(","):
            out.append((m.group(1), name.strip()))
    return out


def strip_heading_suffix(heading: str) -> str:
    """'RunStartedEvent Attributes' -> 'RunStartedEvent'; 'Parameters' -> ''."""
    h = heading.split("(")[0].strip().strip("`")
    words = h.split()
    while words and words[-1].lower() in HEADING_SUFFIX_WORDS:
        words = words[:-1]
    return "".join(words)


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def compare(table_rows: list[dict], sp: SourceParams,
            page_doc_names: set[str] | None = None) -> dict:
    documented: dict[str, dict] = {}
    for r in table_rows:
        documented.setdefault(r["name"], r)
    src = sp.params
    src_active = {k for k, v in src.items() if not v["deprecated"]}
    src_deprecated = {k for k, v in src.items() if v["deprecated"]}
    doc_names = set(documented)

    inherited_documented = sorted(
        n for n in doc_names - set(src)
        if sp.has_kwargs and n in sp.inherited
    )
    documented_properties = sorted(
        n for n in doc_names - set(src) - set(inherited_documented)
        if n in sp.properties
    )
    missing_raw = src_active - doc_names
    # base-class fields documented in another table on the same page (e.g. a
    # "BaseXEvent Attributes" table) are not per-class missing
    covered_elsewhere = sorted(missing_raw & (page_doc_names or set()))
    missing = sorted(missing_raw - set(covered_elsewhere))
    phantom = sorted(doc_names - set(src) - set(inherited_documented)
                     - set(documented_properties))
    documented_aliases = sorted(doc_names & src_deprecated)
    undocumented_aliases = sorted(src_deprecated - doc_names)

    wrong_defaults = []
    for name in sorted(doc_names & set(src)):
        doc_default = norm_default(documented[name]["default"])
        src_default = norm_default(src[name]["default"])
        if not comparable(doc_default) or not comparable(src_default):
            continue
        if doc_default != src_default:
            wrong_defaults.append({
                "param": name,
                "documented": (documented[name]["default"] or "").strip(),
                "actual": src[name]["default"],
            })
    return {
        "documented_count": len(doc_names),
        "source_param_count": len(src),
        "source_active_count": len(src_active),
        "missing": missing,
        "phantom": phantom,
        "documented_aliases": documented_aliases,
        "undocumented_aliases": undocumented_aliases,
        "inherited_documented": inherited_documented,
        "documented_properties": documented_properties,
        "covered_by_other_table_on_page": covered_elsewhere,
        "wrong_defaults": wrong_defaults,
        "accepts_kwargs": sp.has_kwargs,
    }


def parse_override(val: str) -> tuple[str | None, str, bool]:
    is_function = val.endswith("()")
    if is_function:
        val = val[:-2]
    if ":" in val:
        module, name = val.split(":", 1)
        return module, name, is_function
    return None, val, is_function


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not AGNO_SRC.is_dir():
        raise SystemExit(
            f"error: agno source not found at {AGNO_SRC}; "
            "create the ./agno symlink at the repo root or set AGNO_REPO"
        )
    index = build_source_index()
    extractor = AstExtractor(index)
    resolver = Resolver(index, extractor)

    pages = sorted((DOCS_ROOT / "reference").rglob("*.mdx"))
    report_pages = []

    for page in pages:
        rel = str(page.relative_to(DOCS_ROOT))
        entry: dict = {"page": rel}
        if rel in SKIP_PAGES:
            entry["status"] = "UNPARSEABLE"
            entry["reason"] = SKIP_PAGES[rel]
            report_pages.append(entry)
            continue
        raw = page.read_text(encoding="utf-8")
        text, snippets = resolve_snippets(raw)
        fm = parse_frontmatter(text)
        title = fm.get("title", "")
        tables = extract_tables(text)
        if snippets:
            entry["snippets"] = snippets
        if not tables:
            entry["status"] = "UNPARSEABLE"
            entry["reason"] = "no parameter-style table or ResponseField group found"
            report_pages.append(entry)
            continue

        rel_dir = str(Path(rel).parent)
        stem = Path(rel).stem
        page_imports = imports_in_page(text)
        prefs = []
        for d, p in DIR_MODULE_PREF.items():
            if rel_dir.startswith(d):
                prefs = p
                break

        # main target
        override = PAGE_OVERRIDES.get(rel)
        main_target: tuple[str | None, str, bool] | None = None
        if isinstance(override, str):
            main_target = parse_override(override)
        elif rel in PAGE_OVERRIDES:
            main_target = None
        else:
            for cand in resolver.candidates_for(title, rel_dir, stem):
                resolved = resolver.resolve_name(cand)
                if resolved:
                    hint = next((mod for mod, nm in page_imports if nm == resolved), None)
                    main_target = (hint, resolved, False)
                    break
            if main_target is None:
                for mod, nm in page_imports:
                    if nm in index:
                        main_target = (mod, nm, False)
                        break

        main_prefs = prefs
        if main_target and main_target[0]:
            main_prefs = [main_target[0], main_target[0].rsplit(".", 1)[0]] + prefs

        generic_norms = {norm_key(g) for g in GENERIC_HEADINGS}
        grouped: dict[tuple, list[dict]] = {}
        method_tables: list[tuple[str, list[dict]]] = []
        unmapped_tables: list[str] = []
        skipped_tables: list[str] = []

        method_re = re.compile(r"^`?\.?_?[a-z][a-z0-9_]*(\(\))?`?$")

        for t in tables:
            h = t["heading"]
            hkey = norm_key(h)
            if hkey.endswith("properties"):
                skipped_tables.append(h)  # computed @property tables, not init params
                continue
            override_target = TABLE_OVERRIDES.get((rel, norm_key(strip_heading_suffix(h))))
            if override_target:
                mod, cname = override_target.split(":", 1)
                grouped.setdefault((mod, cname, False), []).extend(t["rows"])
                continue
            # try own heading, then ancestor headings (nearest first)
            mapped = False
            for idx, cand_h in enumerate([h] + t.get("chain", [])):
                ckey = norm_key(cand_h)
                stripped = strip_heading_suffix(cand_h)
                if stripped and norm_key(stripped) not in generic_norms:
                    resolved = resolver.resolve_name(stripped)
                    if resolved:
                        hint = main_target[0] if (
                            main_target and resolved == main_target[1]
                        ) else None
                        grouped.setdefault((hint, resolved, False), []).extend(t["rows"])
                        mapped = True
                        break
                if main_target and method_re.match(cand_h.strip()) and ckey not in generic_norms:
                    method_tables.append((cand_h.strip().strip("`").strip(".").rstrip("()"),
                                          t["rows"]))
                    mapped = True
                    break
                # a non-generic heading that is neither class nor method blocks
                # further ancestor walking only if it's the table's own heading
                generic = (
                    ckey in generic_norms
                    or (title and norm_key(title) in ckey)
                    or ckey.endswith(("parameters", "attributes", "fields", "params"))
                )
                if idx == 0 and not generic:
                    break
            if mapped:
                continue
            hkey_generic = (
                hkey in generic_norms
                or (title and norm_key(title) in hkey)
                or hkey.endswith(("parameters", "attributes", "fields", "params"))
            )
            if main_target and (hkey_generic or len(tables) == 1):
                grouped.setdefault(main_target, []).extend(t["rows"])
            else:
                unmapped_tables.append(h or "(no heading)")

        # drop cross-reference rows naming a class (e.g. "inherits
        # BaseWorkflowRunOutputEvent") rather than a parameter
        for rows in list(grouped.values()) + [r for _m, r in method_tables]:
            rows[:] = [r for r in rows
                       if not (r["name"][0].isupper() and r["name"] in index)]

        page_doc_names: set[str] = set()
        for rows in grouped.values():
            page_doc_names.update(r["name"] for r in rows)

        results = []
        for (hint, name, is_fn), rows in grouped.items():
            sp = resolver.get_params(name, hint, is_fn, prefs=main_prefs)
            if sp is None:
                results.append({"class": name, "status": "SOURCE_NOT_FOUND"})
                continue
            cmp = compare(rows, sp, page_doc_names if len(grouped) > 1 else None)
            cmp.update({"class": name + ("()" if is_fn else ""), "module": sp.module,
                        "extraction": sp.method, "status": "OK"})
            results.append(cmp)

        for mname, rows in method_tables:
            if not main_target:
                unmapped_tables.append(mname)
                continue
            sp = resolver.get_method_params(main_target[0], main_target[1], mname, main_prefs)
            if sp is None:
                unmapped_tables.append(mname)
                continue
            cmp = compare(rows, sp)
            cmp.update({"class": f"{main_target[1]}.{mname}()", "module": sp.module,
                        "extraction": sp.method, "status": "OK", "is_method": True})
            results.append(cmp)

        ok = [r for r in results if r.get("status") == "OK"]
        if not ok:
            entry["status"] = "UNPARSEABLE"
            reasons = []
            if not main_target:
                reasons.append(f"could not map title {title!r} to a class in agno source")
            if unmapped_tables:
                reasons.append(f"unmapped tables: {unmapped_tables}")
            if any(r.get("status") == "SOURCE_NOT_FOUND" for r in results):
                reasons.append("mapped class not found in source")
            entry["reason"] = "; ".join(reasons) or "no table mapped to a class"
            report_pages.append(entry)
            continue

        entry["status"] = "OK"
        entry["targets"] = results
        if unmapped_tables:
            entry["unmapped_tables"] = unmapped_tables
        if skipped_tables:
            entry["skipped_property_tables"] = skipped_tables
        entry["totals"] = {
            "missing": sum(len(r["missing"]) for r in ok),
            "phantom": sum(len(r["phantom"]) for r in ok),
            "wrong_defaults": sum(len(r["wrong_defaults"]) for r in ok),
            "documented_aliases": sum(len(r["documented_aliases"]) for r in ok),
            "inherited_documented": sum(len(r["inherited_documented"]) for r in ok),
        }
        report_pages.append(entry)

    ok_pages = [p for p in report_pages if p["status"] == "OK"]
    unparseable = [p for p in report_pages if p["status"] != "OK"]
    totals = {
        "pages_total": len(report_pages),
        "pages_ok": len(ok_pages),
        "pages_unparseable": len(unparseable),
        "missing_total": sum(p["totals"]["missing"] for p in ok_pages),
        "phantom_total": sum(p["totals"]["phantom"] for p in ok_pages),
        "wrong_defaults_total": sum(p["totals"]["wrong_defaults"] for p in ok_pages),
        "documented_aliases_total": sum(p["totals"]["documented_aliases"] for p in ok_pages),
        "inherited_documented_total": sum(p["totals"]["inherited_documented"] for p in ok_pages),
        "pages_with_drift": sum(
            1 for p in ok_pages
            if p["totals"]["missing"] or p["totals"]["phantom"] or p["totals"]["wrong_defaults"]
        ),
        "pages_clean": sum(
            1 for p in ok_pages
            if not (p["totals"]["missing"] or p["totals"]["phantom"] or p["totals"]["wrong_defaults"])
        ),
    }
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agno_source": str(AGNO_SRC),
        "docs_root": str(DOCS_ROOT),
        "notes": [
            "documented_aliases are deprecated alias params still documented: not phantoms.",
            "inherited_documented are params documented on a subclass page that the class "
            "accepts via **kwargs from a parent signature: not phantoms.",
            "wrong_defaults only compares concrete, machine-comparable defaults.",
            "tables under '... Properties' headings are skipped (computed properties).",
        ],
        "totals": totals,
        "pages": report_pages,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(totals, indent=2))
    print(f"\nwrote {OUT_PATH}")
    for p in unparseable:
        print(f"UNPARSEABLE {p['page']}: {p.get('reason', '')[:140]}")


if __name__ == "__main__":
    main()
