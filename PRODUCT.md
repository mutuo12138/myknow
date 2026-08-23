# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- Inferred from the explicit brief: people who collect large amounts of images, webpages, documents, presentations and videos during research or creative work.
- They need to capture quickly while browsing, then return later to review, classify, summarize and retrieve what they saved.

## Product Purpose

Muse Vault is a local-first personal knowledge and material library. It turns deliberately captured browser content and imported local files into an organized, searchable collection with usable previews, editable metadata and optional AI assistance.

Success means a user can save material without interrupting exploration, understand what was saved at a glance, reorganize it directly, recover mistakes and find it again without reopening the original website.

## Positioning

Muse Vault combines polite browser capture, local durable storage, visual material management and optional AI enrichment in one workflow. AI is an opt-in organizing layer, not a requirement for using the library.

## Operating Context

- The development experience currently runs in a local browser at `http://127.0.0.1:5174/`, backed by the local API and worker.
- Content enters through the browser extension, editable shortcuts or local folder import.
- The primary daily surface is a three-part library: navigation and destinations, a visual material canvas, and a focused inspector.
- Common operations are browsing, searching, filtering, previewing, moving to folders or smart categories, editing tags, deleting to trash, restoring and generating offline documents on demand.

## Capabilities and Constraints

- Stores images, webpages, blogs, documents, presentations, links and video references locally.
- Shows generated thumbnails and saved webpage captures where available.
- Supports folders, controlled tags, categories, color and brightness analysis, pagination, recycle-bin recovery and on-demand PDF or Word exports.
- AI modes are off, manual and automatic. Saving provider settings must not itself process or charge for material.
- Destructive deletion must remain recoverable through the recycle bin before permanent deletion.
- Browser capture is deliberate and permission-aware; it must not become bulk scraping.
- Existing data, API contracts and working workflows must be preserved during visual redesign.

## Brand Commitments

- Product name: Muse Vault.
- User-pinned visual direction: a readable, image-first desktop reference workbench with confident typography, high-contrast neutral planes, direct gallery browsing and one restrained blue focus color. It must serve designers, researchers, office workers, creators and general collectors without looking like a generic AI dashboard.
- Inferred interaction commitment: the interface should feel light and approachable without hiding familiar library controls or reducing information density below practical daily use.

## Evidence on Hand

- The formal local library contains real captured image and webpage records used for browser acceptance.
- Existing Eagle and Seek screenshots in `docs/` provide workflow references, not brand assets to copy.
- Automated backend and system acceptance tests cover data integrity, search, AI authorization, export and recycle-bin behavior.
- No testimonials, public customer claims, pricing or production release claims are available and none may be fabricated.

## Product Principles

1. Capture quickly, organize later without losing context.
2. Local files and user corrections outrank generated metadata.
3. Direct manipulation must always have a visible, reversible result.
4. Similar actions belong together; destructive actions remain visually and spatially separate.
5. AI is optional, budget-aware and never silently triggered.

## Accessibility & Inclusion

- Core actions need keyboard alternatives, visible focus, readable contrast and reduced-motion support.
- Drag-and-drop must not be the only way to move or delete material; contextual and inspector actions remain available.
- Frosted transparency requires solid-color fallbacks and must preserve text contrast.
