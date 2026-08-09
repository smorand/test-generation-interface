# Pipeline: what it does, why, and the numbers behind each choice

Read this before touching `agents/distiller.py`, `agents/scenario_generator.py`,
`agents/coverage.py`, `grammar.py` or `coverage_report.py`.

Every figure here was measured on the same document, a 280 000 character functional
specification, with `claude-haiku-4-5`, unless stated otherwise.

## Why the first design was replaced

The first pipeline cut the document into 4000 character blocs and generated tests per bloc.
That tests paragraphs, not an application.

| Measure | Chunk pipeline | Scenario pipeline |
|---|---|---|
| Tests | 2199 | **313** |
| Steps | 7102 | **1130** |
| Review at 2 min per step | about 34 person-days | about **5** |
| Requirements covered | not measurable | **464 of 468, 99 percent** |
| Uncovered | unknown | **0**, plus 9 declared untestable |
| Scenarios | none | 64: 53 nominal, 9 error, 2 limit |
| Failed units | 0 of 88 blocs | **0 of 64 scenarios**, 1 for human review |
| LLM calls | 382 to 691 | **83**: 1 distiller, 64 generator, 18 coverage |
| Waste | 0 to 1 percent | **0 percent**, 1.00 attempt per success |
| Tests on screen detail | **38 percent** | parameterised into data rows |
| Coverage figure | median 100 percent, and wrong | counted, no model involved |

That median of 100 percent is the important one. Each bloc scored coverage of the rules it
had invented for itself, so the judge validated a deliverable nobody could review. A score
can be arithmetically correct and answer the wrong question.

## Phase 0: read the numbering, without a model

A specification numbers its own content and that numbering is the only trustworthy skeleton
available.

| Source | Use cases | Requirements | Fabrications |
|---|---|---|---|
| Regex over the document | **51 of 51** | **401 of 401, 0 orphan** | 0 |
| Model, enumerating | 46 of 51 | 250 references | **0** |
| Model, interrogated about one use case | n/a | **17 where 1 exists** | 16 |

Two rules follow, and they are not style preferences.

**Enumerate, never interrogate.** Asking "what are the rules of F03.EU04.CU04" makes a model
produce a plausible series RM01 to RM17. Asking "list what you see" produced 250 identifiers
with none invented. Same model, same document, different question shape.

**Filter every identifier against the document**, case insensitively. It is a regex and no
call, and it turns a 94 percent fabricated answer into a clean one. The letter suffix form
`RM07a` broke that comparison twice, once in the parser and once in a measurement script:
normalise both sides.

### The grammar is inferred, not assumed

Counting prefixes per position over the whole identifier population gives position 0 as `F`
or `E`, position 1 as `EU`, `M`, `N` or `T`, position 2 as `CU`, position 3 as `RM` or `EM`.
The prefix dominating the deepest shared position is the leaf; the one above is the
container. A document writing `UC` instead of `CU` is read just as well.

**Each family keeps its own depth.** The functional family is four segments (`F.EU.CU.RM`),
the screen family is two (`E.M`, `E.N`). A single global depth silently drops the shorter
family, which is how 205 screen references were once treated as noise.

### The document numbers four families, the first pipeline read one

| Family | Grammar | Volume | What it is |
|---|---|---|---|
| Functional | `F` then `EU` then `CU` then `RM`/`EM` | 590 refs | functionality, user step, use case, requirement |
| Screens | `E` then `M`/`N` | 205 refs | a screen, its messages, its notifications |
| Batch | `T` | 103 mentions | a named process, "T02: Lire les lignes GAC/GN" |
| Prose | none | rest | genuinely unnumbered |

The 404 requirements once parked as unnumbered were mostly screens and batches. They are
also exactly what the 38 percent of screen detail tests were about, and what the
parameterised tests now cover as data rows.

## Phase 1: distil, then let a human validate

The whole document goes in one call when it fits: **78 000 tokens against a 128 000 token
window**. Whether it needs splitting is computed from the reading model's window
(`reading_budget_chars`), never fixed by design.

The model returns context, scenarios and discards. Then arithmetic closes what it missed:

| Step | Use cases with a scenario | Requirements carried |
|---|---|---|
| Model output | 41 of 55 | 201 of 468 |
| After `attach_requirements` | 53 of 55 | **468 of 468** |

A requirement the model did not cite joins the scenario of its own use case; a use case with
requirements and no scenario gets a derived one, flagged as derived so a human can tell it
from a written one. Nothing can be silently dropped.

### What the human validates, and why it is the map

The first version asked a human to validate the **chunking**, a mechanical artefact with no
business meaning. The map is the artefact worth a minute of attention, and the screen states
what is computable without a model: use cases the document declares that no scenario covers,
use cases the document never titles (2 of 51 on the reference document, referenced only
inside their rules), and every proposed discard.

**No filter is silent.** Distillation removes out of scope material and boilerplate, but this
document is almost clean: zero "hors périmètre", one deferral, two "optionnel", one
cartridge. A filter that cannot be validated must be visible, so every removal is shown with
its ground and a human accepts or keeps it. Accepting one takes its references out of the
corpus of truth and is recorded.

## Phase 2: generate per scenario

The unit of work is the scenario. Each call gets the context, the scenario, its requirements
with their statements, and its own section of the document (`section_of`, median 695
characters).

**Volume is a target, not a cap.** A scenario carrying 33 requirements produced 8 tests
covering 27 of them, where the chunk pipeline had produced 95 tests for the same use case.
One of those tests validated 13 requirements at once, which is the point: fewer tests, each
proving more.

Scenario ids give each scenario its own test id range, so a rerun is idempotent.

## Phase 3: close the gaps, editing before adding

What is uncovered is computed, never asked. The model receives the gap and is asked to close
it, preferring to complete an existing test over writing a new one, and it states why in
`coverage_note`. It may declare a requirement untestable in black box rather than fabricate a
test.

An untestable claim is a **model claim**, so it stays in the denominator until a human accepts
it as a discard. That is deliberate: it keeps a model from improving its own score by
declaring the hard requirements out of reach.

## Reading the deliverable: two axes

Scenarios answer "what does this test", requirements answer "is anything forgotten". One axis
alone is what made the first version unreadable.

HTML weight decides where filtering happens: a test card renders about **4.8 kB**, so 1938
tests would push past **9 MB**. Both axes filter and paginate server side, the tests of a
scenario are fetched on expansion, and responses are gzipped, which took the 850 rule tree
from **1.53 MB to 69 kB**, a factor of 22. The `/stream` path is excluded, because gzip
buffers a stream and live progress would arrive in bursts.

## Failure modes, and what they must not do

`LLMJSONError` is an expected outcome: a scenario that produces no usable JSON is marked for
human review, and the run continues. A verdict of the wrong shape leaves its batch
unevaluated, checked at runtime because the `dict` annotation is a promise nothing enforced;
a list verdict once failed whole blocs with `'list' object has no attribute 'get'`.

**Every exception is reported on its scenario.** A swallowed one left 58 scenarios stuck at
running with no trace, and `gather(return_exceptions=True)` is what hid it.

**Locks belong to the loop that runs them.** An `asyncio.Lock` binds to the first loop that
awaits it, so a lock in a module level registry leaked between tests and raised "bound to a
different event loop", making failures depend on test order. `locks.py` keys them by running
loop.

## Two measurement traps

**The gateway caches identical prompts.** A fresh chunk takes 3.2 s, the same chunk again
takes **0.35 s**. Timings from a repeat run of the same document are a cache benchmark, not a
speed measurement. Change the document, or say so.

**A harness that forgets tracing measures nothing.** `configure_tracing()` must be called
explicitly outside the app factory, otherwise no `llm.json_attempt` span is written and
`tgi-stats` reports an empty table on a run that worked.

Span level measurement of the final control run: **83 calls, 0 percent wasted, one attempt per
success, every finish_reason stop, nothing truncated**, medians 56 s for the single distillation
call, 10 s per scenario, 6 s per coverage pass.
