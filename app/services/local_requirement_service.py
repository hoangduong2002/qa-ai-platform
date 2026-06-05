import json

from pathlib import Path


class LocalRequirementService:

    def load_requirement(
        self,
        ticket_id: str
    ):

        base_path = (
            Path("requirements")
            / ticket_id
        )

        ticket_file = (
            base_path
            / "ticket.json"
        )

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

        extracted_dir = (
            base_path
            / "source"
            / "extracted"
        )
        
        additional_notes_dir = (
            base_path
            / "source"
            / "additional_notes"
        )
        
        clarification_answers_dir = (
            base_path
            / "source"
            / "clarification_answers"
        )

        result = {
            "ticket": {},
            "description": "",
            "comments": "",
            "additional_notes": "",
            "clarification_answer_notes": "",
            "uploaded_content": "",
            "uploaded_documents": []
        }

        #
        # Ticket
        #

        if ticket_file.exists():

            try:

                result["ticket"] = json.loads(
                    ticket_file.read_text(
                        encoding="utf-8"
                    )
                )

            except Exception:

                result["ticket"] = {}

        #
        # Description
        #

        if description_file.exists():

            result["description"] = (
                description_file.read_text(
                    encoding="utf-8"
                )
            )

        #
        # Comments
        #

        if comments_file.exists():

            result["comments"] = (
                comments_file.read_text(
                    encoding="utf-8"
                )
            )
            
        #
        # Additional Notes
        #

        additional_notes = []

        if additional_notes_dir.exists():

            for file_path in sorted(
                additional_notes_dir.glob(
                    "*.md"
                )
            ):

                try:

                    content = (
                        file_path.read_text(
                            encoding="utf-8"
                        )
                    )

                    additional_notes.append(
                        f"""
        ==================================================
        NOTE: {file_path.name}
        ==================================================

        {content}
        """
                    )

                except Exception:

                    continue

        result["additional_notes"] = (
            "\n\n".join(
                additional_notes
            )
        )
        
        clarification_answer_notes = []

        if clarification_answers_dir.exists():

            for file_path in sorted(
                clarification_answers_dir.glob("*.md")
            ):

                try:
                    content = file_path.read_text(
                        encoding="utf-8"
                    )

                    clarification_answer_notes.append(
                        f"""
        ==================================================
        CLARIFICATION ANSWERS: {file_path.name}
        ==================================================

        {content}
        """
                    )

                except Exception:
                    continue

        result["clarification_answer_notes"] = (
            "\n\n".join(
                clarification_answer_notes
            )
        )
        
        

        #
        # Uploaded / Extracted Documents
        #

        extracted_contents = []

        if extracted_dir.exists():

            for file_path in sorted(
                extracted_dir.glob("*")
            ):

                if not file_path.is_file():
                    continue

                try:

                    content = (
                        file_path.read_text(
                            encoding="utf-8"
                        )
                    )

                except Exception:

                    continue

                result[
                    "uploaded_documents"
                ].append(
                    {
                        "file_name": file_path.name,
                        "content": content
                    }
                )

                extracted_contents.append(
                    f"""
==================================================
FILE: {file_path.name}
==================================================

{content}
"""
                )

        result["uploaded_content"] = (
            "\n\n".join(
                extracted_contents
            )
        )

        return result


_requirement_service = (
    LocalRequirementService()
)


def get_requirement_service():

    return _requirement_service