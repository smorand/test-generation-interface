# Backlog

**Items 1, 2 and 3 of the original list are built.** The pipeline reads the document whole and
generates per scenario, the volume is a parameter in the interface and in generation, and the
four identifier families are read. What follows is what remains, with the measurement that
justifies each item. See `.agent_docs/pipeline.md` for the numbers of the delivered pipeline.


Decided but not built, with the measurement that justifies each item. Numbers come from the
reference run on the 280 000 character specification (88 blocs, `claude-haiku-4-5`), recorded
in `.agent_docs/pipeline.md`.

## 1. Non functional requirements

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

## 2. Use cases that inherit their rules

The document says "Reprise des règles précédentes" for **3 use cases**, all in the notification
step: they declare no rule of their own and reuse the previous ones. The model reported them as
absent, which was true about rules and misleading about the use case. The map needs a way to say
"this use case inherits the rules of that one", otherwise those 3 look uncovered forever.

## 3. Preconditions belong in fixtures, not in steps

Step reuse across the 7102 steps is only 1.4 (5202 distinct), so a general step library would earn
little. The repetition is concentrated at the start of tests: "accéder à la liste des relations
coverage" 41 times, "se connecter en tant que RRC" 29, "accéder à l'écran E01 composition du
portefeuille" 29. Those are preconditions written as steps. Naming them as fixtures cuts review
volume without losing a single assertion.

## 4. Chat that writes, not only reads

Asked for explicitly. Today the chat answers about the document, the requirements, the tests and
the run, and it modifies nothing. To honour "génère moi deux ou trois tests de plus sur ce
scénario ou cette exigence", it needs tools: generate tests for a target, attach them, and commit.

Constraints that already exist and must hold: every write goes through the state lock and produces
a git commit, the deduplication and the volume target apply to what the chat adds as much as to a
run, and the answer must say what it changed and where to look. The read only contract stays the
default: writing happens only on an explicit request naming a scenario or a requirement.

## 5. Spec change impact analysis

The discard log and the human arbitration of contradictions are built. What is not: comparing
two versions of the same specification. This document is a v5, so a v6 will come.

Distilling both and diffing the scenarios and requirements tells exactly which tests to
replay, rewrite or drop. The pieces are already there, since the distilled corpus is an
artefact of the export and requirements carry stable identifiers. The open risk is a reissue
that renumbers: arbitration decisions and reviewed flags are keyed on identifiers and would
be lost.

## 6. Set cover instead of asking for the minimum

The generator is asked to aim at a volume and the coverage pass prefers editing to adding,
which is prompt discipline, not a guarantee. The deterministic version: let the model propose
candidate tests with the requirements each one covers, then let code pick the minimal
covering subset, which is a set cover with a good greedy approximation. The model proposes,
the code decides, which is the same principle as enumerate rather than interrogate.

Worth measuring first: on the reference run the tests already claim 2.3 requirements each on
average, so the gain may be small.

## 7. Smaller items

- **Splitting a document with no headings. Decided against.** `split_for_reading` cuts on the
  document outline (`\n#`), so a text carrying no heading is never split: measured, 40 000
  characters against a 5 000 character budget came back as one part. The call then overflows the
  window, that part returns nothing, and the map ends up entirely derived, with every requirement
  carried but no context and no proposed discard, on a warning in the log only. Accepted: the
  specifications here are Word files, where the `Titre 1..6` styles become markdown headings, so
  the answer is to write headings. Residual risk to know: a PDF cannot follow that advice, since
  `_parse_pdf` returns page text with no heading at all. Revisit only if a large PDF shows up.

- **Windows and Qwen3.6 end to end.** Never run by the assistant, the only part of the product
  with no first hand verification. `tgi.bat`, then `uv run tgi-validate --model ...`.
- **Old interrupted projects.** Around a hundred projects from the chunk era sit in `projects/`,
  stuck at running or pending, some still showing the judge error of 2026-08-08. They are runtime
  data, safe to delete.
- **Timing measurements on a repeated document are meaningless.** The gateway caches identical
  prompts: a fresh chunk takes 3.2 seconds, the same chunk again takes 0.35. Change the document
  or state that the figure is a cache benchmark.
