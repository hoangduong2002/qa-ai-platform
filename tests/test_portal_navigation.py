from __future__ import annotations

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.web import portal_router
from app.web.portal_router import templates


def _render_layout(path: str = "/portal") -> str:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "query_string": b"",
        }
    )
    return templates.get_template("layout.html").render(request=request)


def _active_navigation_id(html: str) -> str | None:
    match = re.search(
        r'class="primary-navigation-link active"[^>]*'
        r'data-navigation-id="([^"]+)"[^>]*aria-current="page"',
        html,
        re.DOTALL,
    )
    return match.group(1) if match else None


def test_sidebar_renders_toggle_and_all_navigation_items_in_order() -> None:
    html = _render_layout()
    expected = [
        ("requirements", "Requirements", "/portal"),
        ("knowledge-base", "Knowledge Base", "/portal/kb"),
        ("knowledge-system", "Knowledge System", "/portal/knowledge"),
        ("ai-chat", "AI Chat", "/portal/chat"),
        ("report", "Report", "/portal/reports"),
    ]

    assert 'id="navigationToggle"' in html
    assert 'aria-controls="appSidebar"' in html
    assert 'aria-label="Open navigation menu"' in html
    positions = []
    for item_id, label, route in expected:
        marker = f'data-navigation-id="{item_id}"'
        positions.append(html.index(marker))
        assert f'href="{route}"' in html
        assert f'data-tooltip="{label}"' in html
    assert positions == sorted(positions)
    assert html.count('data-navigation-id="') == 5


def test_application_branding_links_to_existing_default_route() -> None:
    html = _render_layout("/portal/reports")

    assert re.search(
        r'<a[^>]*id="portalHeaderBrand"[^>]*class="header-brand-link"'
        r'[^>]*href="/portal"[^>]*>'
        r'\s*<h1>QA AI Platform - Web Portal</h1>',
        html,
        re.DOTALL,
    )
    assert re.search(
        r'<a[^>]*id="portalSidebarBrand"[^>]*class="app-sidebar-brand"'
        r'[^>]*href="/portal"[^>]*>',
        html,
        re.DOTALL,
    )
    assert 'aria-label="QA AI Platform - Web Portal home"' in html
    assert 'aria-label="QA AI Platform home"' in html


def test_brand_navigation_is_semantic_and_has_no_script_reload_handler() -> None:
    html = _render_layout("/portal/chat")
    header_brand = re.search(
        r'<a[^>]*id="portalHeaderBrand"[^>]*>', html, re.DOTALL
    )
    sidebar_brand = re.search(
        r'<a[^>]*id="portalSidebarBrand"[^>]*>', html, re.DOTALL
    )

    assert header_brand
    assert sidebar_brand
    for brand in (header_brand.group(0), sidebar_brand.group(0)):
        assert 'href="/portal"' in brand
        assert "onclick=" not in brand
        assert "tabindex=" not in brand
    assert ".header-brand-link:focus-visible" in html
    assert ".app-sidebar-brand:focus-visible" in html
    assert "window.location" not in header_brand.group(0)
    assert "window.location" not in sidebar_brand.group(0)


def test_old_top_navigation_links_are_removed() -> None:
    html = _render_layout()
    header = html.split("</header>", 1)[0]

    assert "header-link" not in header
    assert header.count('href="/portal"') == 1
    assert 'id="portalHeaderBrand"' in header
    assert 'href="/portal/chat"' not in header
    assert 'href="/portal/knowledge"' not in header
    assert 'href="/portal/kb"' not in header


def test_active_navigation_handles_root_and_nested_routes() -> None:
    expectations = {
        "/portal": "requirements",
        "/portal/": "requirements",
        "/portal/requirements/WEC-123": "requirements",
        "/portal/requirements/WEC-123/knowledge-review": "requirements",
        "/portal/kb": "knowledge-base",
        "/portal/kb/weclever/search": "knowledge-base",
        "/portal/knowledge": "knowledge-system",
        "/portal/chat": "ai-chat",
        "/portal/chat/sessions/session-1": "ai-chat",
        "/portal/reports": "report",
        "/portal/reports/download": "report",
    }
    for path, expected_item in expectations.items():
        assert _active_navigation_id(_render_layout(path)) == expected_item


def test_unknown_route_has_no_active_navigation_item() -> None:
    assert _active_navigation_id(_render_layout("/portal/not-a-real-page")) is None


def test_navigation_uses_one_semantic_landmark_and_inline_icons() -> None:
    html = _render_layout()

    assert html.count('aria-label="Primary navigation"') == 1
    assert html.count('class="primary-navigation-icon"') == 5
    assert html.count("<svg") >= 9
    assert html.count('aria-current="page"') == 1


def test_sidebar_controls_and_accessibility_contract_render() -> None:
    html = _render_layout()

    assert 'id="appSidebar"' in html
    assert 'id="sidebarCollapseButton"' in html
    assert 'id="sidebarPinButton"' in html
    assert 'id="sidebarCloseButton"' in html
    assert 'aria-pressed="true"' in html
    assert 'aria-expanded="true"' in html
    assert 'id="navigationBackdrop"' in html
    assert 'id="portalMainContent"' in html


def test_sidebar_preferences_are_scoped_and_mobile_open_state_is_not_persisted() -> None:
    html = _render_layout()

    assert "qa-ai-platform.sidebar.pinned" in html
    assert "qa-ai-platform.sidebar.expanded" in html
    assert "savePreference(SIDEBAR_PINNED_KEY" in html
    assert "savePreference(SIDEBAR_EXPANDED_KEY" in html
    assert "SIDEBAR_OPEN_KEY" not in html


def test_responsive_close_focus_and_keyboard_behaviors_are_present() -> None:
    html = _render_layout()

    assert 'window.matchMedia("(max-width: 900px)")' in html
    assert 'event.key === "Escape"' in html
    assert 'event.key !== "Tab"' in html
    assert 'backdrop.addEventListener("click"' in html
    assert "toggle.focus()" in html
    assert 'body.classList.toggle("navigation-open"' in html
    assert "@media(prefers-reduced-motion:reduce)" in html


def test_requirement_page_removes_view_report_shortcut(monkeypatch) -> None:
    monkeypatch.setattr(portal_router, "list_requirements", lambda: [])
    app = FastAPI()
    app.include_router(portal_router.router)

    response = TestClient(app).get("/portal")

    assert response.status_code == 200
    assert "Requirement Management" in response.text
    assert "View Report" not in response.text
    assert response.text.count('href="/portal/reports"') == 1
    assert 'data-navigation-id="report"' in response.text
    assert 'href="/portal/requirements/new"' in response.text


def test_report_page_remains_accessible_from_sidebar(monkeypatch) -> None:
    monkeypatch.setattr(
        portal_router,
        "build_report_preview",
        lambda: {
            "summary": {},
            "requirement_rows": [],
            "node_rows": [],
            "log_rows": [],
        },
    )
    app = FastAPI()
    app.include_router(portal_router.router)

    response = TestClient(app).get("/portal/reports")

    assert response.status_code == 200
    assert "QA AI Platform Report Preview" in response.text
    assert "Back to Dashboard" not in response.text
    assert 'data-navigation-id="report"' in response.text
    assert 'aria-current="page"' in response.text
    assert 'href="/portal/reports/download"' in response.text
