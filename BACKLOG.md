# Backlog

Decided but not built, with the measurement that justifies each item. Numbers come from the
reference run on the 280 000 character specification (88 blocs, `claude-haiku-4-5`), recorded
in `.agent_docs/pipeline.md`.

## 1. Read the document as a whole, generate per use case

**Why.** The pipeline chunks mechanically and generates tests per chunk, which tests
paragraphs instead of the application. Measured on the reference run: 2199 tests, 7102 steps,
about **34 person-days of review** at 2 minutes per step, **38 percent of tests on screen
detail** (labels, links, columns, formats) against 25 percent on a business act, up to **129
tests for one use case**, median 22. The judge reports a median score of 100 percent because
it only scores coverage of the rules a chunk invented for itself, so it validates a deliverable
nobody can review.

**Proven feasible.** The document is about **78 000 tokens for a 128 000 token context**, so it
is read in one call. One enumeration pass returned 4 of 4 functionalities, 15 of 16 user steps,
**46 of 51 use cases and 250 rule references with zero invented identifier**, in 35 seconds.
Reading costs **2 calls instead of 88**.

**Refinement from the design discussion.** The first phase is not a map, it is a **distilled
document**: context, scenarios, functional requirements, non functional requirements. Measured on
this specification, the skeleton the document already declares weighs **20 400 tokens, 26 percent
of the raw 77 700**, and even doubled by model written context and scenarios it stays near 40 000.
So the expensive whole document read happens **once**, and every phase after it runs on a substrate
any model can hold. Whether the raw document needs chunking becomes a property of the reading model
alone, computed from its window, not a design constant.

**Two axes, not one.** Scenarios drive test generation, requirements are verified against the tests
produced. A coverage pass then either adds a few tests or **edits existing ones** so they validate
the uncovered requirements, and the interface filters tests by scenario and by requirement. The
current deliverable tree has a single axis (functionality, use case, rule, tests), which is the
real structural gap.

**Target shape.**

1. Skeleton by regex, not by model: the document declares its identifiers, and extraction finds
   **51 of 51 use cases, 401 of 401 rules, 0 orphan, 49 of 51 titles** from the markdown
   headings. The 2 use cases without a title appear only inside rule identifiers and are named
   by the human.
2. One global pass for meaning: grouping, user scenarios, constraints. It never owns the list.
3. Human validates the **map**, not the chunking. The completeness gap is computable without a
   model, so the screen states "51 declared, 48 mapped, 3 missing".
4. Generation per use case (51 calls), with the document sections attached to that use case.
   Blocs survive as evidence, not as units of work.
5. Synthesis per functionality (4 calls): grouping, and parameterised tests for message tables
   and screen details.
6. The judge changes question: coverage of the **declared** use cases and rules, computed
   locally, and it only judges the quality of a test.

**Two rules the measurements impose.**

- **Enumerate, never interrogate.** Asking for the rules of one named use case produced **17
  references where the document declares 1**. Asking the model to list what it sees produced
  250 references with none invented. Same model, same document, different question shape.
- **Filter every identifier against the document**, case insensitively. It is a regex and no
  call. The letter suffix form `RM07a` broke this comparison twice, once in `parse_source_ref`
  and once in a measurement script.

**Not proven yet.** The generation half. Attaching the right document sections to a use case is
untested, and so is whether the 16 000 token output budget holds for a use case carrying 24
rules.

## 2. The document numbers four axes, the pipeline recognised one

Measured on the identifier population, with no hardcoded convention:

| Axis | Grammar | Volume | What it is |
|---|---|---|---|
| Functional | `F` then `EU` then `CU` then `RM` or `EM` | 590 refs | functionality, user step, use case, requirement |
| Screens | `E` then `M` or `N` | 205 refs | a screen, its messages, its notifications |
| Batch | `T` | 103 mentions | a batch process, "T02: Lire les lignes GAC/GN" |
| Free text | none | rest | genuinely unnumbered prose |

The 404 rules parked in « Hors numérotation » are mostly the screen and batch axes, so they
were never noise: `E01.N02` is a notification of screen `E01`, `T02` is a named process. This
is also what the measured **38 percent of tests on screen detail** really are, and it is exactly
the material for one parameterised test per screen, its messages and notifications as rows.

**The grammar is inferrable, so stop hardcoding it.** Counting prefixes by position gives
position 0 as `F` or `E`, position 1 as `EU`, `M`, `N` or `T`, position 2 as `CU`, position 3 as
`RM` or `EM`. The level that dominates position 2 is the use case, whatever it is called in the
next document. `parse_source_ref` currently hardcodes `CU`, which is an overfit to this
specification and will silently mislabel any document that writes `UC` or `CDU`.

## 3. Tests per use case as a parameter

**Decided.** The number of tests per use case must be a parameter, exposed in the interface and
honoured by generation. At 5 tests per use case this specification yields **255 tests against
2199 today, 8.6 times fewer**.

Specification to implement with item 1, since nothing consumes it before then. No control was
added to the interface in the meantime: a field wired to nothing is worse than no field.

- Setting `TGI_TESTS_PER_USE_CASE`, default 5, accepted range 1 to 20.
- Editable per project on the import form, next to the model choices, and stored in the state so
  a rerun keeps it.
- The generator receives it as a target, not a hard cap: a use case with 24 rules may need more,
  and the synthesis pass is what enforces the ceiling.
- Likely replaces `TGI_MAX_TESTS_PER_RULE`, which caps at the wrong level.

## 4. Non functional requirements

**Measured before deferring.** This specification carries almost none: **zero** occurrence of
performance, response time, accessibility or browser compatibility, and only sécurité (21) and
disponibilité (30) as loose mentions. Building an extractor for them now would target a document
type never observed. The deferral is evidence based, not a shortcut.

**Requirements already carry a type.** The document numbers **258 RM** and **222 EM**, so it
distinguishes business rules from business requirements by itself, and the pipeline flattened both
into "rules". A requirement is the object, the type is an attribute, and the type is what should
drive how it gets verified. Business rules are requirements: the model has one class too few.

**Set aside on purpose, to refine later.** The pipeline has no notion of them today: it extracts
business rules and generates functional tests. Nothing in the extractor, the generator or the
judge distinguishes a performance, security, availability or accessibility requirement from a
business rule, so those requirements are either silently treated as business rules or dropped
with the paragraph they came from.

Open when it is picked up: whether they are classified during the global pass, whether they get
their own chapter in the deliverable next to the functionalities, and whether a test is the
right artefact for them at all.

## 5. Use cases that inherit their rules

The document says "Reprise des règles précédentes" for **3 use cases**, all in the notification
step: they declare no rule of their own and reuse the previous ones. The model reported them as
absent, which was true about rules and misleading about the use case. The map needs a way to say
"this use case inherits the rules of that one", otherwise those 3 look uncovered forever.

## 6. Preconditions belong in fixtures, not in steps

Step reuse across the 7102 steps is only 1.4 (5202 distinct), so a general step library would earn
little. The repetition is concentrated at the start of tests: "accéder à la liste des relations
coverage" 41 times, "se connecter en tant que RRC" 29, "accéder à l'écran E01 composition du
portefeuille" 29. Those are preconditions written as steps. Naming them as fixtures cuts review
volume without losing a single assertion.

## 7. Chat that writes, not only reads

Asked for explicitly. Today the chat answers about the document, the requirements, the tests and
the run, and it modifies nothing. To honour "génère moi deux ou trois tests de plus sur ce
scénario ou cette exigence", it needs tools: generate tests for a target, attach them, and commit.

Constraints that already exist and must hold: every write goes through the state lock and produces
a git commit, the deduplication and the volume target apply to what the chat adds as much as to a
run, and the answer must say what it changed and where to look. The read only contract stays the
default: writing happens only on an explicit request naming a scenario or a requirement.

## 8. A discard log, because no filter may be silent

Distillation drops what is not useful: out of scope items, features deferred to a later version,
versioning cartouches, prose that helps nobody test. Measured on this specification, that noise is
**almost absent**: zero "hors périmètre", one deferral, two "optionnel", one cartouche. So the
filter cannot be validated here, which makes a silent filter dangerous: it would drop the wrong
things with no way to notice.

Every removal is therefore recorded and shown: what was dropped, and on which ground. The same
screen carries the human arbitration of contradictions, since both produce the same object, a
decision that removes something from the corpus of truth. One feature, not two.

The arbitrations must survive a re distillation, so they are keyed on the document's own
identifiers. Open risk: a specification reissued as v6 with renumbered identifiers loses them.

## 9. Smaller items

- **Bloc number alignment.** Sorting is fixed and numeric everywhere. Padding the display to
  `bloc-0009` was proposed and not done, because the identifier is used in the routes, the chat
  and the export. Only the visual alignment is missing, if it is still wanted.
- **Windows and Qwen3.6 end to end.** Never run by the assistant, the only part of the product
  with no first hand verification. `tgi.bat`, then `uv run tgi-validate --model ...`.
- **Old interrupted projects.** Several 78 bloc projects sit in `projects/` with blocs stuck at
  running or pending, and they still display the judge error fixed on 2026-08-08. They are runtime
  data, safe to delete.
- **Timing measurements on a repeated document are meaningless.** The gateway caches identical
  prompts: a fresh chunk takes 3.2 seconds, the same chunk again takes 0.35. Change the document
  or state that the figure is a cache benchmark.
