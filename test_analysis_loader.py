from app.utils.analysis_loader import (
    load_analysis
)

analysis = load_analysis(
    "DEMO-001"
)

print(analysis["actors"])
print(analysis["business_rules"])