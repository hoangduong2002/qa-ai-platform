import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import figma_requirement_service
from app.services import jira_requirement_service
from app.utils import file_extractors


class ImageVisionExtractionTests(unittest.TestCase):
    def test_image_extraction_uses_local_vision_when_allowed(self):
        with patch.object(
            file_extractors,
            "_current_ai_mode",
            return_value="PRODUCTION_HYBRID",
        ), patch.object(
            file_extractors,
            "resolve_provider_for_task",
            return_value={"provider": "LOCAL_VISION"},
        ), patch.object(
            file_extractors,
            "extract_image_with_LOCAL",
            return_value="# Screen/Image Summary\nVisible content",
        ) as extract_image:
            result = file_extractors._extract_image_text(Path("screen.png"))

        self.assertIn("Visible content", result)
        extract_image.assert_called_once_with(Path("screen.png"))

    def test_image_extraction_skips_when_vision_not_allowed(self):
        with patch.object(
            file_extractors,
            "_current_ai_mode",
            return_value="DEEPSEEK_ONLY",
        ), patch.object(
            file_extractors,
            "resolve_provider_for_task",
            return_value={"provider": "SKIP"},
        ), patch.object(
            file_extractors,
            "extract_image_with_LOCAL",
        ) as extract_image:
            result = file_extractors._extract_image_text(Path("screen.png"))

        self.assertEqual(result, file_extractors.IMAGE_VISION_SKIPPED_MESSAGE)
        extract_image.assert_not_called()

    def test_test_local_only_missing_vision_raises_friendly_error(self):
        with patch.object(
            file_extractors,
            "_current_ai_mode",
            return_value="TEST_LOCAL_ONLY",
        ), patch.object(
            file_extractors,
            "resolve_provider_for_task",
            return_value={"provider": "SKIP"},
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Local Vision is required in TEST_LOCAL_ONLY mode",
            ):
                file_extractors._extract_image_text(Path("screen.png"))

    def test_jira_and_figma_skip_messages_use_local_vision_skip_marker(self):
        self.assertEqual(
            jira_requirement_service.VISION_ANALYSIS_SKIPPED_MESSAGE,
            file_extractors.IMAGE_VISION_SKIPPED_MESSAGE,
        )
        self.assertEqual(
            figma_requirement_service._vision_skip_message("NO_LLM"),
            file_extractors.IMAGE_VISION_SKIPPED_MESSAGE,
        )


if __name__ == "__main__":
    unittest.main()
