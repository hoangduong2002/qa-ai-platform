from graph.nodes.load_requirement import (
    load_requirement
)

from graph.nodes.analyze_requirement import (
    analyze_requirement
)

state = {
    "ticket_id": "DEMO-001"
}

state.update(
    load_requirement(state)
)

result = analyze_requirement(
    state
)

print(result)