from app.utils.artifact_loader import load_ticket_artifacts
from app.utils.review_session import load_review_session

from graph.nodes.improve_testcases import improve_testcases
from graph.nodes.final_review_coverage import final_review_coverage


def run_improve_cycle(ticket_id: str):
    state = load_ticket_artifacts(
        ticket_id
    )

    session = load_review_session(
        ticket_id
    )

    version = (
        "v"
        + str(
            session.get(
                "improve_iterations",
                0
            )
        )
    )

    state["improve_version"] = version

    improve_result = improve_testcases(
        state
    )

    state.update(
        improve_result
    )

    final_review_result = final_review_coverage(
        state
    )

    state.update(
        final_review_result
    )

    return state