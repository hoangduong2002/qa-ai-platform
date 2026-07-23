# Knowledge Package import

Bulk import adds collections and documents to an existing Knowledge Base while
leaving all manual create, upload, publish, archive, supersede and reindex
operations unchanged.

## Package layout

ZIP is the recommended production format. A representative package is:

```text
weclever_rag_knowledge/
|-- README.md
|-- collection_manifest.json
|-- weclever-domain/
|   |-- reference_tables.md
|   `-- domain_taxonomy.json
|-- weclever-business-rules/
|   `-- business_rules_from_expected_results.jsonl
|-- weclever-api/
|   `-- api_technical_test_knowledge.jsonl
|-- weclever-integrations/
|   `-- integration_test_knowledge.jsonl
|-- weclever-test-cases/
|   `-- billing/payment_cases.jsonl
|-- weclever-defects/
|   `-- defect_rejection_knowledge.jsonl
`-- weclever-project-guidelines/
    `-- project_profile.json
```

Each direct child directory is one collection. Nested directories remain part
of that collection. Root README files are ignored; the optional root
`collection_manifest.json` is returned as package metadata. Hidden paths,
`__MACOSX`, `.DS_Store`, `Thumbs.db`, and similar operating-system artifacts are
ignored.

Create a ZIP while retaining the root folder:

```powershell
Compress-Archive -Path .\weclever_rag_knowledge -DestinationPath .\weclever_rag_knowledge.zip
```

```bash
zip -r weclever_rag_knowledge.zip weclever_rag_knowledge/
```

## IDs and supported documents

Collection IDs are derived from top-level folder names. Names are trimmed,
lowercased, spaces become hyphens, unsupported characters are removed, and the
result must satisfy the existing 2-128 character identifier validation. The
preview always shows the original and normalized names. Two folders that
normalize to the same ID block the import.

Document IDs are deterministic: their collection-relative path is joined with
hyphens and the final extension is removed. A short path checksum is appended
only when normalized paths collide. The original filename, relative path,
extension and package name remain visible in the plan; imported documents store
the package-relative source in `external_id`.

The parser registry is the source of truth. Currently supported extensions are
Markdown (`.md`, `.markdown`), JSON (`.json`), JSONL (`.jsonl`) and text
(`.txt`, `.text`, `.log`). Unsupported files are listed and skipped without
blocking other documents.

Package JSONL is parsed and emitted one non-empty record at a time from the
source stream; the full file is never loaded into memory. A string `content`
field becomes the record's chunk text. Other records remain serialized JSON.
Malformed lines report their original line number. The current `ChunkRecord`
schema has no generic metadata field, so JSONL fields other than `content`
cannot be stored as separate chunk metadata yet.

## Portal workflow

1. Open `/portal/kb/<kb_id>` and find **Import Knowledge Package**.
2. Select a ZIP or a browser folder, choose `skip` or `fail`, enter the existing
   maintainer token, and select **Inspect Package**.
3. Review collections, files, warnings, normalization, unsupported formats,
   conflicts and fatal errors. Inspection does not mutate storage.
4. Select the same package in the confirmation form. Optionally use **Dry run**
   or explicitly enable **Auto-publish**, then select **Import Package**.
5. Review per-collection and per-document results. The normal manual forms are
   still available on the same page.

REST clients use:

- `POST /api/knowledge/bases/{kb_id}/packages/inspect`
- `POST /api/knowledge/bases/{kb_id}/packages/import`
- header `X-Maintainer-Token`
- multipart field `zip_file`, or repeated `folder_files`

Portal routes are:

- `POST /portal/kb/{kb_id}/packages/inspect`
- `POST /portal/kb/{kb_id}/packages/import`
- form field `maintainer_token_value`

## Conflict and publication behavior

`skip` is the default. Existing collections are reused and existing document
IDs or content checksums are skipped. `fail` blocks before known conflicts can
mutate storage. Published/indexed documents are never overwritten. Repeating a
`skip` import is safe and reports reused/skipped items.

Auto-publish is off by default. When explicitly enabled, each uploaded document
is published through the existing service, which also rebuilds the index. No
additional reindex is run. Partial failures are reported and an import-level
audit event is appended without document content or tokens.

Document versioning remains fixed at version 1. Package import does not pretend
to replace, revise or overwrite an existing document safely; use manual
supersede/archive workflows instead.

## Security limits

```env
KB_PACKAGE_MAX_COMPRESSED_SIZE_BYTES=52428800
KB_PACKAGE_MAX_UNCOMPRESSED_SIZE_BYTES=209715200
KB_PACKAGE_MAX_FILE_COUNT=2000
KB_PACKAGE_MAX_DIRECTORY_DEPTH=12
KB_PACKAGE_MAX_COMPRESSION_RATIO=100
KB_PACKAGE_ALLOWED_ARCHIVE_TYPES=zip
```

`KNOWLEDGE_BASE_MAX_FILE_SIZE_BYTES` continues to apply unchanged to individual
manual uploads. It does not apply to package members. Package imports instead
enforce the configured compressed archive size, total uncompressed size, file
count, directory depth, allowed archive type, and per-member compression ratio.

The package pipeline is separate from manual upload. API upload spools are
passed directly to the importer, ZIP metadata is inspected from the central
directory, and members are opened as streams only when validated or ingested.
Archives are not extracted to the filesystem; the importer does not create an
in-memory byte copy of the complete ZIP or of individual members. Absolute paths,
traversal, null bytes, backslashes, symbolic links, encrypted members,
excessive depth, file count, total size, and compression ratio are rejected.

For rollback, stop using the package routes; no storage migration or feature
replacement is involved. Existing imported documents can be handled with the
normal archive/supersede controls. Disabling `KNOWLEDGE_BASE_ENABLED` disables
both manual and package Knowledge Base routes.
