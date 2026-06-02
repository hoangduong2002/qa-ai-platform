from graph.testcase_graph import graph

result = graph.invoke(
    {
        "ticket_id":
        "DEMO-001"
    }
)

print(
    result["coverage_review"]
)