from fastapi import FastAPI
from pydantic import BaseModel

from graph.testcase_graph import graph


app = FastAPI(
    title="QA AI Platform",
    version="0.1.0"
)


class GenerateTestcaseRequest(BaseModel):
    ticket_id: str


@app.get("/health")
def health():
    return {
        "status": "ok"
    }


@app.post("/generate-testcases")
def generate_testcases(
    request: GenerateTestcaseRequest
):
    result = graph.invoke(
        {
            "ticket_id": request.ticket_id
        }
    )

    return {
        "ticket_id": request.ticket_id,
        "analysis": result.get("analysis"),
        "scenarios": result.get("scenarios"),
        "testcases": result.get("testcases"),
        "coverage_review": result.get("coverage_review")
    }
    
@app.post("/generate-testcases-summary")
def generate_testcases_summary(
    request: GenerateTestcaseRequest
):
    result = graph.invoke(
        {
            "ticket_id": request.ticket_id
        }
    )

    return {
        "ticket_id": request.ticket_id,
        "total_scenarios": len(result.get("scenarios", [])),
        "total_testcases": len(result.get("testcases", [])),
        "coverage_score": result.get("coverage_review", {}).get("coverage_score"),
        "missing_coverage": result.get("coverage_review", {}).get("missing_coverage", []),
        "recommendations": result.get("coverage_review", {}).get("recommendations", [])
    }