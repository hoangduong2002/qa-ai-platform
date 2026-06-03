from langgraph.graph import StateGraph, END

from app.models.state import QAState

from graph.nodes.load_requirement import load_requirement
from graph.nodes.analyze_requirement import analyze_requirement
from graph.nodes.generate_clarifications import generate_clarifications
from graph.nodes.generate_test_scope import generate_test_scope
from graph.nodes.generate_scenarios import generate_scenarios
from graph.nodes.generate_testcases import generate_testcases
from graph.nodes.review_coverage import review_coverage
from graph.nodes.improve_testcases import improve_testcases
from graph.nodes.final_review_coverage import final_review_coverage


builder = StateGraph(QAState)

builder.add_node(
    "load_requirement",
    load_requirement
)

builder.add_node(
    "analyze_requirement",
    analyze_requirement
)

builder.add_node(
    "generate_clarifications",
    generate_clarifications
)

builder.add_node(
    "generate_test_scope",
    generate_test_scope
)

builder.add_node(
    "generate_scenarios",
    generate_scenarios
)

builder.add_node(
    "generate_testcases",
    generate_testcases
)

builder.add_node(
    "review_coverage",
    review_coverage
)

builder.add_node(
    "improve_testcases",
    improve_testcases
)

builder.add_node(
    "final_review_coverage",
    final_review_coverage
)

builder.set_entry_point(
    "load_requirement"
)

builder.add_edge(
    "load_requirement",
    "analyze_requirement"
)

builder.add_edge(
    "analyze_requirement",
    "generate_clarifications"
)

builder.add_edge(
    "generate_clarifications",
    "generate_test_scope"
)

builder.add_edge(
    "generate_test_scope",
    "generate_scenarios"
)

builder.add_edge(
    "generate_scenarios",
    "generate_testcases"
)

builder.add_edge(
    "generate_testcases",
    "review_coverage"
)

builder.add_edge(
    "review_coverage",
    "improve_testcases"
)

builder.add_edge(
    "improve_testcases",
    "final_review_coverage"
)

builder.add_edge(
    "final_review_coverage",
    END
)

graph = builder.compile()