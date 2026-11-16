# Backend handoff acceptance — 2026-09-14

Local Backend HTTP + Gateway + real model. No Frontend source change or shared-server deployment.

| Check | Evidence |
| --- | --- |
| Existing bound Skill read | turn_51f29057cc3449a7a32625166172eb9f, expected receipt observed |
| Normally published Skill resource/script | turn_7f997cadcd244f9792044940736b2df8, execution receipt and workspace proof |
| Same filename, separate users | turn_b01facb731d944cfb55161342400686e and turn_a3b93e6ecdac4c05bafda2494c6edf3b, own DOCX marker only |
| Markdown / ambiguity / missing | turn_17fc9a1fd350464581cb8dab40843460 / turn_2e0bc69c701d409aaead4e248efce4fc / turn_c420f02f5e1d493db825af58fc629afa |
| Temporary attachment content | turn_3b2be42c670f4b45af45115d90245fe2, exact random receipt, delivery use_count=1 |
| Disconnect, snapshot, cursor replay | turn_ecb87d5f857948708c3ffdb88950129f, continued to completion, reconstructed text equals final, unique ordered ids |
| No duplicate execution/charge | same continuation Turn, session Turn count=1, usage record=1, charge record=1 |
| Actual cancellation | turn_05d2268bc97647bdbec23dd0e10ba82b, subprocess started before cancel, delayed write absent afterward |
| Restart | turn_e1368f4896d3446b9e394e4ba792cde7, running -> failed/interrupted, partial text preserved |

Concurrent POST returned 409, future cursor 400, foreign-user read 404.
235 focused and required tests passed; Ruff and diff whitespace checks passed.
Storage tests cover pagination-independent aggregation, expired pending-GC bytes, reservations,
delete, release and reconciliation. Additional formats were not individually tested with a model.

Limitations: original reported Skill permission denial was not reproduced in the current bound
Expert. Existing isolation was retained. An earlier explicit permanent attachment had real read
provenance but an inaccurate model answer, so it is not an answer-correctness pass. The later
temporary delivery succeeded after configuring the absolute delivery origin.
The local BFF turn route returned 404; these checks are not browser-page acceptance.
Execution ownership currently requires one Backend worker.

Temporary Expert and Skill deleted, uploaded test files reclaimed, test sessions soft-deleted,
four dedicated test users disabled. Existing business Expert preserved.
