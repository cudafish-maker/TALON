# Mobile Documents

Mobile documents are planned as fetch/cache first.

## Required Workflows

- List synced document metadata.
- Fetch document over active broadband Reticulum link.
- Store encrypted local cache.
- Open/share using Android-safe intents only after warning where appropriate.
- Evict stale cache when core reports hash/version changes or delete.

## Constraints

- Mobile upload is deferred.
- First fetch requires network path accepted by core.
- Large files should avoid LoRa.
- Macro-risk warnings are required before saving/opening risky office formats.
