# myknow Architecture

## Deliberate collection, not crawling

The extension only sends a capture after a user right-clicks or long-presses an asset. It sends page metadata, selected/visible text, and a media reference. The host does not batch-fetch sites, bypass logins, or download protected streams.

## Flow

```text
Browser extension
  -> POST 127.0.0.1:8765/api/captures
  -> SQLite WAL material + folder + canonical/content-hash identity + capture operation
  -> staging write + atomic final placement + recoverable path commit
  -> local worker: controlled image download / 640px WebP thumbnail / classify / visual features / AI enrichment / PDF-Word export / trigram FTS index
  -> explicit finalizer: ready only when required jobs are done; dead jobs produce partial/failed
  -> local React workspace: cursor-like paging, folder, category, stacked tags, color, brightness and Chinese full-text search
```

## AI pipeline boundaries

| Stage | Current MVP | Upgrade path |
| --- | --- | --- |
| Text | Rules + FTS5 | OpenAI-compatible text model or local embedding index |
| Images | Palette, brightness, detail score | Vision-capable OpenAI-compatible model or local CLIP captions + embeddings |
| Video | Consent-gated queue state | whisper.cpp transcript + sampled keyframes |
| Offline web | Sanitized HTML + extracted text | rendered snapshot and embedded assets |
| Search | FTS title/text/tags + exact stacked tags | CLIP/text embeddings with local vector index |

## Data integrity boundary

- Every connection uses SQLite WAL, a 30-second busy timeout, foreign keys, and `synchronous=NORMAL`.
- `capture_operations` records planned staging and final paths before file writes begin.
- Completed staging files are atomically moved into `data/assets`; interrupted operations are resumed or marked failed at startup.
- `material_derivatives` tracks rebuildable thumbnails separately from originals; cards read derivatives while detail view loads originals on demand.
- Unreferenced partial outputs are quarantined under `data/recovery`, not silently presented as saved materials.
- `/api/integrity` reports missing files, orphan files, stale/duplicate FTS rows, dead jobs marked ready, and incomplete capture operations.
- Permanent regression and acceptance evidence lives under `tests/`; it uses isolated `MUSE_VAULT_HOME` directories and never writes to the formal user database.

The data model keeps the original, derived text, visual descriptors and jobs separate, so changing an AI provider does not rewrite the original capture.

## Storage and secrets

- Original user-provided data URL assets: `data/assets/{type}/{folder-id}/`.
- Rebuildable 640px WebP thumbnails: `data/assets/derivatives/thumbnail/{folder-id}/`.
- Captured webpage HTML and offline exports: `data/assets/web/{folder-id}/`.
- Database and metadata: `data/muse-vault.db`.
- AI configuration: `data/ai-config.json`; API keys are encrypted with current-user Windows DPAPI and never returned by the API.
- Browser extension never receives or stores API keys.
- Vision API requests use a generated JPEG preview capped at 1280px and 1.5MB; original images are never inserted directly into the request body.
- Videos are retained as a source reference until an explicitly permitted local media workflow is added.
