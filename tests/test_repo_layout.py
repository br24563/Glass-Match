"""Repository layout guards.

A `.gitignore` rule once excluded `tests/fixtures/demo.agf` along with the
redistribution-limited manufacturer catalogs, so the fixture was never
committed and every fresh clone - including CI - failed collection with
FileNotFoundError. Separately, `import yaml` was never declared in
requirements.txt: the author's venv had PyYAML as a side effect of a
screenshot tool, so the gap was invisible locally and fatal everywhere else.
These tests fail loudly and early if either recurs.
"""
import ast
import sys
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

REQUIRED_FIXTURES = ["demo.agf"]


@pytest.mark.parametrize("name", REQUIRED_FIXTURES)
def test_required_fixture_exists(name):
    path = FIXTURES / name
    assert path.exists(), (
        f"missing test fixture: {path}. Synthetic fixtures must be committed - "
        "check that .gitignore does not exclude tests/fixtures/.")


def test_fixture_is_synthetic_not_a_manufacturer_catalog():
    """Fixtures ship with the tests, so they must not be a real catalog dump.

    demo.agf legitimately carries N-BK7's CC0 Sellmeier coefficients (documented
    in its header) to exercise the nd cross-check. What must never happen is a
    whole manufacturer catalog being committed here, so the guard is on size and
    on the required provenance note rather than on glass names.
    """
    path = FIXTURES / "demo.agf"
    text = path.read_text(encoding="utf-8", errors="replace")
    nm_records = [ln for ln in text.splitlines() if ln.strip().startswith("NM ")]
    assert len(nm_records) <= 5, (
        f"fixture has {len(nm_records)} NM records - that looks like a real "
        "catalog dump, not a test fixture")
    assert "refractiveindex.info" in text, (
        "fixture must document the provenance of any real coefficients it uses")


def test_required_data_files_exist():
    for name in ("manufacturers.csv", "glasses.csv", "properties.csv",
                 "sources.csv", "sellmeier.csv", "transmission.csv"):
        assert (ROOT / "data" / "normalized" / name).exists(), \
            f"missing committed data file: data/normalized/{name}"


def test_no_manufacturer_catalogs_are_committed():
    """Redistribution policy: no real .agf catalog may be tracked.

    Only synthetic fixtures under tests/fixtures/ are allowed.
    """
    try:
        out = subprocess.run(["git", "ls-files", "*.agf", "*.AGF"],
                             cwd=ROOT, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git not available")
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    tracked = [p for p in out.stdout.split() if p.strip()]
    offenders = [p for p in tracked
                 if not p.replace("\\", "/").startswith("tests/fixtures/")]
    assert not offenders, (
        "manufacturer catalogs must not be committed (redistribution-limited): "
        + ", ".join(offenders))


# --- declared dependencies -------------------------------------------------
# `import yaml` sat in requirements.txt nowhere, so every fresh clone - CI and
# every new user - hit ModuleNotFoundError. The local venv had PyYAML only
# because a screenshot-capture tool had installed it, which is exactly why this
# class of bug hides from the author. Every third-party import must be declared.
STDLIB = set(sys.stdlib_module_names)
LOCAL_ROOTS = {"glassmatch", "scripts", "tests", "app", "conftest", "pytest"}
# Imported only by optional dev tooling, never by the app or the test suite.
OPTIONAL = {"playwright"}
# Distributions whose import name is not a suffix of the PyPI name.
ALIASES = {"sklearn": "scikit-learn", "cv2": "opencv-python", "PIL": "pillow",
           "dateutil": "python-dateutil"}
VERSION_SEPARATORS = ("==", ">=", "<=", "~=", "!=", ">", "<", "=")


def _third_party_imports():
    found = {}
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in {".venv", ".git", "__pycache__", "build", "dist"}:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                if name in STDLIB or name in LOCAL_ROOTS:
                    continue
                found.setdefault(name.lower(), set()).add(str(rel).replace("\\", "/"))
    return found


def _declared_requirements():
    """Package names from requirements*.txt, comments and flags stripped.

    The first version of this mis-parsed: it skipped any token containing '=',
    which threw away every pinned requirement (numpy>=1.26, pyyaml>=6.0, ...),
    and it matched comment prose such as a bare '-' against everything, because
    '' is a substring of every string. The guard therefore passed with the very
    bug it was written to catch.
    """
    names = set()
    for filename in ("requirements.txt", "requirements-dev.txt"):
        path = ROOT / filename
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):  # -r, -e, --index-url
                continue
            for token in line.split():
                pkg = token.split("[", 1)[0]
                for sep in VERSION_SEPARATORS:
                    if sep in pkg:
                        pkg = pkg.split(sep, 1)[0]
                        break
                pkg = pkg.strip().lower()
                if pkg:
                    names.add(pkg)
    return names


def _is_satisfied(module, packages):
    mod = ALIASES.get(module, module).replace("-", "").replace("_", "")
    if len(mod) < 3:  # never let a trivially short name match everything
        return False
    return any(mod == p.replace("-", "").replace("_", "")
               or p.replace("-", "").replace("_", "").endswith(mod)
               for p in packages)


def test_every_third_party_import_is_declared():
    declared = _declared_requirements()
    assert declared, "could not parse any requirement - is requirements.txt present?"
    undeclared = {m: sorted(u) for m, u in _third_party_imports().items()
                  if m not in OPTIONAL and not _is_satisfied(m, declared)}
    assert not undeclared, (
        "these modules are imported but not declared in requirements*.txt, so a "
        "fresh clone will fail:\n  "
        + "\n  ".join(f"{m} <- {', '.join(u)}" for m, u in undeclared.items()))


def test_the_guard_detects_a_missing_declaration():
    """A guard that cannot fail is worse than none. Prove this one bites.

    Drops PyYAML from the parsed requirement set - reproducing the original
    bug - and asserts both dependency tests then fail.
    """
    declared = _declared_requirements()
    assert _is_satisfied("yaml", declared), (
        "PyYAML should satisfy 'import yaml'; if this fails the satisfaction "
        "rule is too strict to be trusted")
    assert _is_satisfied("numpy", declared), (
        "a pinned requirement like 'numpy>=1.26' must still be recognised")
    without = {p for p in declared if p != "pyyaml"}
    assert not _is_satisfied("yaml", without), (
        "removing pyyaml must make 'import yaml' undeclared - otherwise this "
        "guard cannot fail and proves nothing")
    # A comment must not be able to satisfy a module name.
    assert not _is_satisfied("yaml", {"-", "#", "parsing", "comments"})


def _first_party_modules():
    """Map importable local module name -> file, for reachability analysis."""
    modules = {}
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in {".venv", ".git", "__pycache__", "build", "dist"}:
            continue
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        modules[".".join(parts)] = path
    return modules


def _file_imports(path):
    """(first-party, third-party) top-level module names imported by a file.

    ast.walk deliberately includes function bodies: a lazy `from x import y`
    inside a function is still a runtime dependency, which is precisely how the
    PyYAML gap reached the running app without appearing in app.py's imports.
    """
    local, external = set(), set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return local, external
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import, stays inside the package
                continue
            if node.module:
                names = [node.module]
        for name in names:
            root = name.split(".")[0]
            if root in LOCAL_ROOTS:
                local.add(name)
            elif root not in STDLIB:
                external.add(root)
    return local, external


def _app_reachable_third_party():
    """Every third-party module the running app can reach, transitively."""
    modules = _first_party_modules()
    third_party = set()
    seen = set()
    queue = ["app"]
    while queue:
        name = queue.pop()
        if name in seen or name not in modules:
            continue
        seen.add(name)
        local, external = _file_imports(modules[name])
        third_party |= external
        for dep in local:
            if dep in modules:
                queue.append(dep)
            else:  # `from glassmatch.x import y` where x is a module
                parent = dep.rsplit(".", 1)[0]
                if parent in modules:
                    queue.append(parent)
    return third_party


def test_app_runtime_dependencies_are_declared():
    """What the *running app* can reach, transitively - not just app.py's imports.

    PyYAML reached the app through a function-local import inside
    glassmatch/database.py, so a scan of app.py alone reported nothing missing
    while every fresh clone would have crashed the moment a user opened a
    crystal and asked for its index at a wavelength.
    """
    declared = _declared_requirements()
    undeclared = sorted(m for m in _app_reachable_third_party()
                        if m.lower() not in OPTIONAL
                        and not _is_satisfied(m.lower(), declared))
    assert not undeclared, (
        "the app can reach undeclared module(s) at runtime, so a fresh clone "
        f"will crash: {undeclared}")


def test_reachability_analysis_finds_the_lazy_import():
    """Guard the guard: prove the traversal sees function-local imports.

    If this fails, test_app_runtime_dependencies_are_declared would silently
    narrow to app.py's own imports and stop catching transitive gaps.
    """
    assert "yaml" in _app_reachable_third_party(), (
        "database.py imports the yaml-backed module inside a function; the "
        "traversal must follow it or it detects nothing")


def test_the_guard_detects_a_missing_declaration():
    """A guard that cannot fail is worse than none. Prove this one bites.

    Drops PyYAML from the parsed requirement set - reproducing the original
    bug - and asserts it is then reported as undeclared.
    """
    declared = _declared_requirements()
    assert _is_satisfied("yaml", declared), (
        "PyYAML should satisfy 'import yaml'; if this fails the satisfaction "
        "rule is too strict to be trusted")
    assert _is_satisfied("numpy", declared), (
        "a pinned requirement like 'numpy>=1.26' must still be recognised")
    without = {p for p in declared if p != "pyyaml"}
    assert not _is_satisfied("yaml", without), (
        "removing pyyaml must make 'import yaml' undeclared - otherwise this "
        "guard cannot fail and proves nothing")
    # A comment must not be able to satisfy a module name.
    assert not _is_satisfied("yaml", {"-", "#", "parsing", "comments"})
