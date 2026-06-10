from app.services.figma_requirement_service import (
    load_figma_node,
    extract_figma_elements,
    build_requirement_context,
)

node = load_figma_node("figma_node_7_228516.json")
elements = extract_figma_elements(node)
requirement_context = build_requirement_context(elements)

print(requirement_context)