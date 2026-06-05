from langgraph.graph import StateGraph, END

from app.models.state import QAState

from graph.nodes.load_requirement import load_requirement
from graph.nodes.analyze_requirement import analyze_requirement
from graph.nodes.generate_requirement_summary import generate_requirement_summary


builder = StateGraph(QAState)

builder.add_node("load_requirement", load_requirement)
builder.add_node("analyze_requirement", analyze_requirement)
builder.add_node("generate_requirement_summary", generate_requirement_summary)

builder.set_entry_point("load_requirement")

builder.add_edge("load_requirement", "analyze_requirement")
builder.add_edge("analyze_requirement", "generate_requirement_summary")
builder.add_edge("generate_requirement_summary", END)

requirement_summary_graph = builder.compile()