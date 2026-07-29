---
description: Who/what/when/where precision and audience separation for ALL writing
---

# Writing Precision — Who / What / When / Where

Applies to **every** artifact Cascade produces: markdown documents, diagram
labels, chat replies, commit messages, PR/issue bodies, code comments, and
docstrings. Imprecision about actors, objects, timing, or environment is a
critical failure — it confuses readers and, for customer-facing material,
actively loses trust.

---

## Rule 1: Name the Who / What / When / Where — Never Leave It Ambiguous

Every statement must let the reader identify, without guessing:

- **Who** — the actor performing the action (a named team/role/component).
- **What** — the specific object acted on (a named file/artifact/system).
- **When** — the phase or point in time (build time, post-build, one-time
  setup, Phase 1, Phase 2, runtime).
- **Where** — the environment or location (the native build machine, the
  analysis harness image, the CI runner, a specific path).

**NEVER** use an ambiguous pronoun (`it`, `they`, `this`, `that`, `you`) or a
bare noun (`the image`, `the platform`, `the build`, `the team`) unless the
referent is unmistakable from the immediately preceding words. When in doubt,
repeat the explicit noun.

---

## Rule 2: The Chat Audience Is NOT the Document Audience

The audience of a Cascade chat reply is the **developer/user** (e.g., the
repository owner). The audience of a markdown document is **whoever the
document is written for** — often a completely different party (e.g., an
enterprise native-build team or a platform/security reviewer).

- **NEVER** carry the conversational `you` from chat into a document. In a
  document, replace `you`/`your` with the explicitly named actor
  (for example, "the native build team", "the native build").
- **ALWAYS** decide and state the document's audience before writing, and
  keep every sentence addressed to that audience.
- A clear sentence in chat is **not** automatically correct in a document.
  Re-target it: swap conversational pronouns for named actors.

---

## Rule 3: Project Actor & Object Vocabulary (use these exact terms)

<table>
<colgroup><col style="width:30%"><col style="width:70%"></colgroup>
<thead><tr><th>Term</th><th>Precise meaning</th></tr></thead>
<tbody>
<tr><td><strong>native build</strong></td><td>The customer's unmodified build: their source, build files (<code>Makefile</code>/<code>pom.xml</code>/etc.), compiler, build commands, and output binaries. This NEVER changes.</td></tr>
<tr><td><strong>native build team</strong></td><td>The customer team that owns and runs the native build.</td></tr>
<tr><td><strong>native build machine / CI runner</strong></td><td>The customer-controlled host/container where the native build executes.</td></tr>
<tr><td><strong>platform team</strong></td><td>MUST be qualified. Usually the customer's own DevOps/platform team that does one-time setup. NEVER let it read as the Bisbom vendor.</td></tr>
<tr><td><strong>analysis harness / our image</strong></td><td>THIS repository's Docker image and pipeline. Distinct from the customer's CI build image. Never conflate the two.</td></tr>
</tbody>
</table>

- **NEVER** write bare "the platform" — say "the native build team's platform
  team" or "the bisbom-gen analysis harness", whichever is meant.
- **NEVER** write bare "the image" — say "the native build's CI image" or
  "the analysis harness image".

---

## Rule 4: Accuracy Over Reassurance — State the Exact Footprint

Do not soften or over-claim to make something sound less invasive than it is.

- Separate the invariant from the variable: "the **native build** never
  changes" (true) is a different claim from "where a **file** is placed"
  (a one-time infra choice with options). State each precisely.
- **NEVER** claim "X does not change" when X does change in some option
  (e.g., baking a file into an image DOES add a file to that image). Name the
  option and its exact footprint.
- Prefer an options table (with an explicit "changes the native build?"
  column) over a single reassuring sentence.

---

## Rule 5: Self-Check Before Finishing Any Writing

Before completing any document, diagram, or non-trivial chat reply, scan every
sentence and confirm:

- [ ] Each actor is named (no bare `it`/`they`/`this`/`you`).
- [ ] Each object is a specific named file/artifact/system.
- [ ] The phase (when) and environment (where) are explicit where relevant.
- [ ] Conversational `you` from chat has NOT leaked into a document.
- [ ] The customer's native build/image/team is not conflated with the
      bisbom-gen analysis harness.
- [ ] No claim over-reassures; footprints are stated exactly.
