"""The seam, checked from this side: public agentloop API only, no configuration reads."""

import ast
from pathlib import Path

import agentloop

SOURCES = sorted((Path(__file__).parent.parent / "src" / "agentloop_tools").rglob("*.py"))


def trees() -> list[tuple[Path, ast.AST]]:
    return [(path, ast.parse(path.read_text())) for path in SOURCES]


def test_only_agentloops_public_api_is_imported() -> None:
    public = set(agentloop.__all__)
    for path, tree in trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("agentloop"):
                assert node.module == "agentloop", f"{path.name} imports {node.module}"
                private = {alias.name for alias in node.names} - public
                assert not private, f"{path.name} imports non-public {sorted(private)}"
            if isinstance(node, ast.Import):
                assert not any(a.name.startswith("agentloop.") for a in node.names), path.name


def test_the_library_never_reads_configuration() -> None:
    """Keys and settings are the application's to read and pass in."""
    for path, tree in trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
                raise AssertionError(f"{path.name} reads os.{node.attr}")
            if isinstance(node, ast.Import | ast.ImportFrom):
                names = [a.name for a in node.names] + [getattr(node, "module", "") or ""]
                assert not any(n.startswith("dotenv") for n in names), path.name


def test_there_is_something_to_check() -> None:
    assert SOURCES, "no sources found: the layering tests would pass vacuously"
