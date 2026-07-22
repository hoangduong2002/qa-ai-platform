from app.services.coverage_model.service import run_coverage_model_builder


def build_coverage_model(state: dict) -> dict:
    return run_coverage_model_builder(state)
