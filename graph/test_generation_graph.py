from langgraph.graph import StateGraph, END

from app.models.state import QAState

from graph.nodes.generate_test_scope import generate_test_scope
from graph.nodes.generate_scenarios import generate_scenarios
from graph.nodes.generate_testcases import generate_testcases


builder = StateGraph(QAState)

builder.add_node("generate_test_scope", generate_test_scope)
builder.add_node("generate_scenarios", generate_scenarios)
builder.add_node("generate_testcases", generate_testcases)

builder.set_entry_point("generate_test_scope")

builder.add_edge("generate_test_scope", "generate_scenarios")
builder.add_edge("generate_scenarios", "generate_testcases")
builder.add_edge("generate_testcases", END)

test_generation_graph = builder.compile()