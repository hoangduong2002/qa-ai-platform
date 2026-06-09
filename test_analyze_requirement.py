from dotenv import load_dotenv

from graph.nodes.load_requirement import (
    load_requirement,
)

from graph.nodes.analyze_requirement import (
    analyze_requirement,
)

from app.services.requirement_sanitization_service import (
    sanitize_requirement_for_analysis,
)


load_dotenv()

state = {
    "ticket_id": "EVNWCL-5221",
}

state.update(
    load_requirement(state)
)

print("Loaded keys:", state.keys())

state["raw_requirement"] = sanitize_requirement_for_analysis(
    ticket_id=state["ticket_id"],
    raw_requirement=state["raw_requirement"],
)

result = analyze_requirement(
    state
)

print(result)