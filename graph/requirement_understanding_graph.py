from langgraph.graph import StateGraph, END

from app.models.state import QAState

from graph.nodes.load_requirement import load_requirement
from graph.nodes.analyze_requirement import analyze_requirement
from graph.nodes.generate_clarifications import generate_clarifications
from graph.nodes.generate_test_scope import generate_test_scope


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
    END
)

requirement_understanding_graph = builder.compile()