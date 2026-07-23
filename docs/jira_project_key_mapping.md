# Jira Project Key mapping

Knowledge Bases can store one or more Jira Project Keys as metadata. This is
preparation for future automatic Knowledge Base selection during Jira
requirement analysis; this release does **not** change Jira import, requirement
analysis, retrieval, or prompt behavior.

`kb_id` remains the stable Knowledge Base identifier and filesystem directory.
Jira Project Keys are separate metadata. One Knowledge Base can own multiple
keys, but a normalized key can belong to only one Knowledge Base. Keys are
trimmed, uppercased, deduplicated in first-seen order, and validated against
`^[A-Z][A-Z0-9_]{0,31}$`.

The canonical source of truth is each Knowledge Base's
`knowledge_base.json`:

```json
{
  "kb_id": "weclever",
  "name": "WeClever Knowledge Base",
  "jira_project_keys": ["WEC", "WECDEV"]
}
```

Existing metadata without `jira_project_keys` remains valid and is read as an
empty list. No migration or Knowledge Base directory rename is required.

## Portal

Open `/portal/kb`. The create form accepts an optional comma-separated list,
for example `WEC, WECDEV`. The Knowledge Base detail page displays every
assigned key and provides a maintainer-only edit form. Submitting an empty list
removes all assignments.

## REST API

Create using JSON (the existing form request remains supported):

```http
POST /api/knowledge/bases
X-Maintainer-Token: <token>
Content-Type: application/json

{
  "kb_id": "weclever",
  "name": "WeClever Knowledge Base",
  "description": "Knowledge for WeClever",
  "jira_project_keys": ["WEC", "WECDEV"]
}
```

Replace or remove assignments without changing other metadata:

```http
PATCH /api/knowledge/bases/weclever
X-Maintainer-Token: <token>
Content-Type: application/json

{"jira_project_keys": ["WEC", "WECSUP"]}
```

The read-only resolution endpoint does not require the maintainer token:

```http
GET /api/knowledge/bases/resolve?jira_project_key=wec
```

```json
{
  "jira_project_key": "WEC",
  "resolved": true,
  "knowledge_base": {
    "kb_id": "weclever",
    "name": "WeClever Knowledge Base",
    "jira_project_keys": ["WEC", "WECSUP"]
  }
}
```

An unknown valid key returns HTTP 200 with `resolved: false`. Invalid keys
return HTTP 400. Assigning a key owned by another Knowledge Base returns HTTP
409 and identifies both the key and current owner.
