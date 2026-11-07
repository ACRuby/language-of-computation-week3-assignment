# ERD — agreed schema (Decision 5)

Per [Decision 5](rules-comparison.md): the group adopted **Kristina's
two-table schema** (`books` + `warnings`) as the shared base, with
`goodreads_book_id` added and indexed as the new identity field (Decision
1). This matches the schema already live in
`week3-assignment/books.db`/`ingest.py` as of this update — Anthony and
Abigail still need to update their own database structures to match.

```mermaid
erDiagram
    books ||--o{ warnings : "has"

    books {
        int id PK "surrogate key"
        string book_id
        string goodreads_book_id "identity field (Decision 1) - indexed, never blank"
        string best_book_id "volatile metadata (Decision 4) - freely updatable"
        string work_id "identity-relevant (Decision 4) - frozen once set"
        string books_count "volatile metadata - freely updatable"
        string isbn "repaired/warned per rules.md section 1; frozen once set (Decision 4)"
        string isbn13 "repaired/warned per rules.md section 1; frozen once set (Decision 4)"
        string authors "identity-relevant - frozen once set"
        string original_publication_year "identity-relevant - frozen once set"
        string original_title
        string title "identity-relevant, case-insensitive (Decision 6) - frozen once set"
        string language_code "identity-relevant - frozen once set"
        string average_rating "volatile metadata - freely updatable"
        string ratings_count "volatile metadata - freely updatable"
        string work_ratings_count "volatile metadata - freely updatable"
        string work_text_reviews_count "volatile metadata - freely updatable"
        string ratings_1 "volatile metadata - freely updatable"
        string ratings_2 "volatile metadata - freely updatable"
        string ratings_3 "volatile metadata - freely updatable"
        string ratings_4 "volatile metadata - freely updatable"
        string ratings_5 "volatile metadata - freely updatable"
        string image_url "volatile metadata - freely updatable"
        string small_image_url "volatile metadata - freely updatable"
        string identity_key "mirrors goodreads_book_id as of Decision 1 - indexed"
        string fallback_key "legacy from ISBN-based identity - no longer used for matching"
        string source_file
        string first_loaded_at
        string last_updated_at
    }

    warnings {
        int id PK "surrogate key"
        int book_row_id FK "references books.id"
        string field "which column the warning is about"
        string raw_value "original offending value, kept for audit"
        string reason "reason code(s), comma-separated when more than one applies (Open item: implement)"
        string recorded_at
    }
```

## What changed from the pre-meeting schema

- **`goodreads_book_id` and `identity_key` are now indexed** (added
  directly to `week3-assignment/ingest.py` and the live `books.db`).
- **`identity_key`'s meaning changed**: it used to be the ISBN-13 (derived
  from a valid ISBN-10 when needed). Per Decision 1 it should now simply
  mirror `goodreads_book_id` — this is a logic change still to be made in
  `ingest.py`'s `compute_identity_key()`, not yet implemented.
- **`fallback_key` is now vestigial.** It existed solely to support manual
  review of no-ISBN books under the old ISBN-based identity model (§2 of
  the original `rules.md`). Since every row now has a `goodreads_book_id`,
  there's no "unidentified book" case left for it to help with. It's kept
  in the schema for now rather than dropped unilaterally — worth a quick
  yes/no from the group on whether to remove it.
- **No new tables or columns were added for the skipped open items**
  (publication-year validation, missing-title/author handling, language
  code, the external lookup/correction workflow) — those stay out of
  scope per the Open Items vote in `rules.md`.

See [`rules.md`](rules.md) §2–§3 for exactly which fields are
"volatile metadata" (freely updatable) versus "identity-relevant" (frozen
once set, reject + review on conflict) — the annotations above mirror that
split directly.

## In Abigail's build

The schema above is implemented as drawn in `ingest.py` (`SCHEMA`), and
`books.db` was rebuilt from scratch on 2026-11-07:

- Every `books` column is `TEXT`; `id` is the integer surrogate key.
- `goodreads_book_id` has a **unique** index; `identity_key` is indexed and
  is set to `goodreads_book_id` (the Decision 1 change described above is
  done here).
- `fallback_key` exists but is always empty, pending the group's yes/no.
- `isbn` and `isbn13` also have plain indexes, so the `isbn-collision`
  check stays fast.
- `warnings.reason` holds every applicable reason code, comma-separated.
  A book's warnings are replaced when it is updated, so re-runs don't pile
  them up (`rules.md` §5, note 8).
- Abigail's earlier tables (`runs`, `audit_log`, `review_items`,
  `rejected_rows`) were removed. Change history (old → new diffs),
  repairs and rejections are recorded per run in `ingestion-log.json`.
