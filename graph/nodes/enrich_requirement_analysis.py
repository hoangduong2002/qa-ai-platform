from app.services.requirement_enrichment.service import run_requirement_enrichment


def enrich_requirement_analysis(state: dict) -> dict:
    return run_requirement_enrichment(state)
