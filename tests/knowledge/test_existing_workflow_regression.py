from __future__ import annotations

from graph.testcase_graph import graph


def test_graph_import_and_compile_regression_smoke() -> None:
    # Smoke check to ensure KB module does not alter graph wiring/imports.
    assert graph is not None
