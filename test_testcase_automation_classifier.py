from app.services.testcase_automation_classifier import (
    classify_testcases_automation,
    classify_testcase_automation,
)
from graph.nodes.generate_testcases import (
    _normalize_compact_testcases,
    _validate_testcases_for_function,
    normalize_generated_testcase,
)
from graph.nodes.improve_testcases import merge_improved_testcases


def _scenario():
    return {
        "scenario_id": "SC001",
        "function_id": "FUNC012",
        "sub_function_id": "SUB001",
        "test_area_id": "AREA001",
        "related_requirement_ids": ["REQ001"],
    }


def _validate_one(testcase):
    _validate_testcases_for_function(
        testcases=[testcase],
        function_id="FUNC012",
        expected_scenario_ids={"SC001"},
    )


def test_login_form_validation_is_automation():
    testcase = classify_testcase_automation(
        {
            "title": "Login form validation shows error for invalid password",
            "priority": "High",
            "test_steps": [
                "Navigate to the login page",
                "Input username 'qa@example.com'",
                "Input invalid password",
                "Click Login",
            ],
            "expected_results": [
                "Display error message 'Invalid credentials'",
            ],
        }
    )

    assert testcase["execution_type"] == "AUTOMATION"
    assert testcase["automation_candidate"] is True
    assert testcase["automation_tool"] == "Playwright"
    assert testcase["automation_priority"] == "High"
    assert testcase["automation_reason"]
    assert testcase["manual_reason"] == ""


def test_visual_layout_usability_is_manual():
    testcase = classify_testcase_automation(
        {
            "title": "Review visual layout and usability of dashboard",
            "priority": "Medium",
            "test_steps": [
                "Open the dashboard",
                "Review color, spacing, and look and feel",
            ],
            "expected_results": [
                "Layout and usability are acceptable to a human reviewer",
            ],
        }
    )

    assert testcase["execution_type"] == "MANUAL"
    assert testcase["automation_candidate"] is False
    assert testcase["automation_priority"] == "Not Applicable"
    assert "layout" in testcase["automation_blockers"]
    assert testcase["manual_reason"]


def test_email_sms_third_party_approval_is_manual_or_hybrid():
    testcase = classify_testcase_automation(
        {
            "title": "Verify third-party approval notification",
            "priority": "High",
            "test_steps": [
                "Submit request",
                "Check email inbox and SMS message",
                "Confirm third-party approval is received",
            ],
            "expected_results": [
                "Approval is visible in the external system",
            ],
        }
    )

    assert testcase["execution_type"] in {"MANUAL", "HYBRID"}
    assert set(testcase["automation_blockers"]).intersection(
        {"email inbox", "sms", "third-party", "approval", "external system"}
    )


def test_partial_ui_flow_with_manual_final_verification_is_hybrid():
    testcase = classify_testcase_automation(
        {
            "title": "Submit onboarding form with manual final verification",
            "priority": "Medium",
            "test_steps": [
                "Navigate to onboarding",
                "Input user profile details",
                "Click Submit",
                "Complete manual verification of the final approval document",
            ],
            "expected_results": [
                "Submission confirmation is displayed",
                "Manual verification confirms approval details",
            ],
        }
    )

    assert testcase["execution_type"] == "HYBRID"
    assert testcase["automation_candidate"] is True
    assert testcase["automation_tool"] == "Playwright"
    assert "manual verification" in testcase["automation_blockers"]
    assert testcase["automation_reason"]
    assert testcase["manual_reason"]


def test_old_testcase_missing_classification_fields_gets_defaults():
    testcase = classify_testcase_automation(
        {
            "testcase_id": "TC001",
            "title": "Legacy exploratory notes",
            "priority": "Low",
            "test_steps": ["Review requirement manually"],
            "expected_results": ["Notes are captured"],
        }
    )

    assert testcase["execution_type"] == "MANUAL"
    assert testcase["automation_candidate"] is False
    assert testcase["automation_tool"] == ""
    assert testcase["automation_priority"] == "Not Applicable"
    assert "automation_reason" in testcase
    assert "automation_blockers" in testcase
    assert "manual_reason" in testcase


def test_invalid_execution_type_is_normalized():
    testcase = classify_testcase_automation(
        {
            "title": "Search users",
            "execution_type": "SCRIPTED",
            "automation_candidate": False,
            "priority": "Medium",
            "test_steps": [
                "Navigate to user list",
                "Input search text",
                "Click Search",
            ],
            "expected_results": ["Search results are displayed"],
        }
    )

    assert testcase["execution_type"] == "AUTOMATION"
    assert testcase["automation_candidate"] is True
    assert testcase["automation_tool"] == "Playwright"


def test_improve_merge_preserves_classification_fields():
    original = [
        {
            "testcase_id": "TC001",
            "scenario_id": "SC001",
            "function_id": "FUNC001",
            "test_area_id": "AREA001",
            "title": "Login succeeds",
            "technique": "EP",
            "test_steps": ["Navigate to login", "Input valid credentials", "Click Login"],
            "expected_results": ["Dashboard is displayed"],
            "related_requirement_ids": ["REQ001"],
            "execution_type": "AUTOMATION",
            "automation_candidate": True,
            "automation_tool": "Playwright",
            "automation_priority": "High",
            "automation_reason": "Browser UI flow with deterministic assertion.",
            "automation_blockers": [],
            "manual_reason": "",
        }
    ]
    patch = [
        {
            "testcase_id": "TC001",
            "title": "Login succeeds with valid credentials",
        }
    ]

    merged = merge_improved_testcases(original, patch)

    assert merged[0]["title"] == "Login succeeds with valid credentials"
    assert merged[0]["execution_type"] == "AUTOMATION"
    assert merged[0]["automation_candidate"] is True
    assert merged[0]["automation_tool"] == "Playwright"
    assert merged[0]["automation_priority"] == "High"
    assert merged[0]["automation_reason"]


def test_testcase_id_alias_is_converted_to_test_case_id():
    testcase = normalize_generated_testcase(
        {
            "testcase_id": "TC0012",
            "scenarioId": "SC001",
            "testSteps": "Open page\nClick Save",
            "expectedResult": "Saved message is displayed",
        }
    )

    assert testcase["test_case_id"] == "TC0012"
    assert testcase["testcase_id"] == "TC0012"
    assert testcase["scenario_id"] == "SC001"
    assert testcase["steps"] == ["Open page", "Click Save"]
    assert testcase["test_steps"] == ["Open page", "Click Save"]
    assert testcase["expected_results"] == ["Saved message is displayed"]


def test_missing_automation_fields_are_filled_by_classifier():
    normalized = _normalize_compact_testcases(
        [
            {
                "test_case_id": "TC001",
                "scenario_id": "SC001",
                "title": "Search users",
                "priority": "High",
                "steps": ["Navigate to users", "Input search text", "Click Search"],
                "expected_result": ["Search results are displayed"],
            }
        ],
        [_scenario()],
    )

    classified = classify_testcases_automation(normalized)

    assert classified[0]["execution_type"] == "AUTOMATION"
    assert classified[0]["automation_candidate"] is True
    assert classified[0]["automation_blockers"] == []
    _validate_one(classified[0])


def test_automation_blockers_string_becomes_list():
    testcase = normalize_generated_testcase(
        {
            "test_case_id": "TC001",
            "automation_blockers": "email inbox\nmanual verification",
        }
    )

    assert testcase["automation_blockers"] == [
        "email inbox",
        "manual verification",
    ]


def test_automation_candidate_string_becomes_boolean():
    testcase = normalize_generated_testcase(
        {
            "test_case_id": "TC001",
            "automation_candidate": "false",
        }
    )

    assert testcase["automation_candidate"] is False


def test_old_testcase_format_still_validates_after_normalization():
    normalized = _normalize_compact_testcases(
        [
            {
                "testcase_id": "TC001",
                "scenario_id": "SC001",
                "title": "Review saved profile",
                "priority": "Medium",
                "preconditions": "User is logged in",
                "test_steps": ["Open profile", "Click Save"],
                "expected_results": ["Profile is saved"],
            }
        ],
        [_scenario()],
    )
    classified = classify_testcases_automation(normalized)

    _validate_one(classified[0])
    assert classified[0]["test_case_id"] == "TC001"
    assert classified[0]["testcase_id"] == "TC001"
