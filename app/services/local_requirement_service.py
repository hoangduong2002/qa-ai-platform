import json
from pathlib import Path


class LocalRequirementService:

    def load_requirement(self, ticket_id: str):

        base_path = Path("requirements") / ticket_id

        ticket_file = base_path / "ticket.json"

        description_file = (
            base_path
            / "source"
            / "description.md"
        )

        comments_file = (
            base_path
            / "source"
            / "comments.md"
        )

        result = {
            "ticket": {},
            "description": "",
            "comments": ""
        }

        if ticket_file.exists():
            result["ticket"] = json.loads(
                ticket_file.read_text(
                    encoding="utf-8"
                )
            )

        if description_file.exists():
            result["description"] = description_file.read_text(
                encoding="utf-8"
            )

        if comments_file.exists():
            result["comments"] = comments_file.read_text(
                encoding="utf-8"
            )

        return result