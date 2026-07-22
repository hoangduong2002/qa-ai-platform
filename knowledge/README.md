# Knowledge Base Module

Independent production-usable file-based Knowledge Base.

## Feature Flag

Set `KNOWLEDGE_BASE_ENABLED=true` to enable API and UI routes.

## CLI

```powershell
python -m knowledge.cli.main validate-kb --kb-id <KB_ID>
python -m knowledge.cli.main rebuild-index --kb-id <KB_ID>
python -m knowledge.cli.main check-health --kb-id <KB_ID>
python -m knowledge.cli.main verify-filesystem-metadata --kb-id <KB_ID>
python -m knowledge.cli.main recover --kb-id <KB_ID>
```

## APIs

Base path: `/api/knowledge`

Write endpoints require header: `X-Maintainer-Token: <token>`.
