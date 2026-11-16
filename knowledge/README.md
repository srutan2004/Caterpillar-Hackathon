# knowledge/

Human-reviewed content only (§7.7). Items arrive here exclusively through `uv run tp review approve`.

* `manuals/<class>/<section>.md` — manual sections with frontmatter (`machine_class`, `section`, `procedure_ids`);
  indexed into Qdrant in Phase 3 (`tp index`).
* `quizzes/*.json` — quiz questions, each grounded in a manual chunk (`source_chunk_id`); loaded by `tp gen`.
* `notes/paraphrases.json` — cab-note paraphrases used by the generator.

The structured fault-code catalogue and parts catalogue live in `config/maintenance/` and are exported by `tp gen`.
