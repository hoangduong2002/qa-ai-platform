from app.services.testcase_automation_classifier import (
    classify_testcase_automation,
)
from graph.nodes.improve_testcases import merge_improved_testcases


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
