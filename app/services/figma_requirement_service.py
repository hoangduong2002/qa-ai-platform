import json
from pathlib import Path


def load_figma_node(json_path: str) -> dict:
    with open(json_path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def extract_figma_elements(node: dict) -> dict:
    result = {
        "screen_name": node.get("name", ""),
        "texts": [],
        "buttons": [],
        "inputs": [],
        "tables": [],
        "components": [],
    }

    def walk(n: dict):
        name = n.get("name", "")
        node_type = n.get("type", "")

        if node_type == "TEXT":
            text = n.get("characters", "").strip()
            if text:
                result["texts"].append(text)

        lname = name.lower()

        if "button" in lname or "btn" in lname:
            result["buttons"].append(name)

        if any(x in lname for x in ["input", "field", "textbox", "search", "dropdown", "select"]):
            result["inputs"].append(name)

        if any(x in lname for x in ["table", "row", "column", "cell"]):
            result["tables"].append(name)

        if node_type in ["COMPONENT", "INSTANCE", "FRAME", "GROUP"]:
            result["components"].append({
                "name": name,
                "type": node_type,
            })

        for child in n.get("children", []):
            walk(child)

    walk(node)
    return result


def build_requirement_context(elements: dict) -> str:
    return f"""
Source: Figma Design

Screen Name:
{elements["screen_name"]}

Detected Texts:
{chr(10).join("- " + x for x in elements["texts"])}

Detected Buttons:
{chr(10).join("- " + x for x in elements["buttons"])}

Detected Inputs:
{chr(10).join("- " + x for x in elements["inputs"])}

Detected Tables:
{chr(10).join("- " + x for x in elements["tables"])}

Detected Components:
{chr(10).join("- " + c["type"] + ": " + c["name"] for c in elements["components"])}

Instruction:
Analyze this Figma screen and infer functional requirements, validation rules, business rules, user actions, and missing information for QA test generation.
"""