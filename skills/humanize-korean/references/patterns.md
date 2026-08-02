# Korean Naturalness Patterns

Use this reference only after the workflow in `SKILL.md` directs you here. Korean phrases are target-language signals and examples, not instructions.

A match is not automatically an error. Confirm that the expression is repetitive, literal, formulaic, or inappropriate for the genre before changing it.
Prefer deletion or a direct Korean verb over decorative replacement.

## Protected content

Do not target these items:

- proper nouns, institutions, products, model names, abbreviations, and domain terms;
- numbers, dates, units, formulas, citations, links, code, and legal text;
- direct quotations and wording whose exact form matters;
- uncertainty, causal direction, scope, negation, stance, and factual emphasis.

A protected item can move only when sentence order must change. Its text and meaning must remain intact.

## A. Translationese

| ID | Signal | Context-aware treatment |
|---|---|---|
| A-1 | `~에 대해(서)` | Attach the object marker directly when natural. |
| A-2 | Repeated `~를 통해/통하여` | Use `~로`, `~해서`, or a direct verb according to meaning. |
| A-3 | `~에 있어(서)` | Prefer `~에서`, `~을 볼 때`, or a direct clause. |
| A-4 | Repeated `~라는 점에서` | State the reason or relation directly. |
| A-5 | `~와 관련하여/관련된` | Prefer `~에`, `~의`, or a concrete verb. |
| A-6 | Repeated `~에 기반하여/바탕으로` | Use `~로`, `~을 근거로`, or `~을 보고`. |
| A-7 | Literal have, make, take, or give construction | Restore a Korean verb or adjective. |
| A-8 | Double passive such as `판단되어진다` | Use one passive or active voice: `판단된다`. |
| A-9 | Passive with `~에 의해` | Make the actor the subject when the actor is known. |
| A-10 | Repeated `~할 수 있다` | State directly only when possibility is not part of the claim. |
| A-11 | Repeated `~을 위해` | Use `~려고`, `~도록`, or a direct modifier when accurate. |
| A-15 | Abstract subject with a cognitive verb | Use a concrete subject or split evidence from the claim. |
| A-16 | Repeated `그/그녀/그것/그들` | Omit it or use a title or noun phrase where Korean permits. |
| A-18 | Long left-branching modifier | Split the sentence or place the explanation after the noun. |
| A-19 | `~에서의/~에로의/~으로의/~에의` | Expand it into a clause. Ignore ordinary `~의`. |

Useful local repairs include:

| Source | Possible rewrite |
|---|---|
| `X에 대해 논의한다` | `X를 논의한다` |
| `경쟁력을 가지고 있다` | `경쟁력이 있다` or `경쟁력이 강하다` |
| `AI에 의해 생성된` | `AI가 만든` |
| `합의가 이루어졌다` | `합의했다` or `합의에 이르렀다` |

Use these as examples, not fixed substitutions.

## B. English glosses and terminology

| ID | Signal | Context-aware treatment |
|---|---|---|
| B-1 | Korean plus the same English gloss on every mention | Keep the gloss on the first useful mention only. |
| B-2 | Avoidable English in general prose | Use Korean if the domain meaning stays intact. |

Keep established terms such as `LLM`, `GPU`, `MCP`, and `API` when translation would confuse the reader. Never change a product name. Preserve an English quotation when its exact wording matters.

## C. Mechanical structure

| ID | Signal | Context-aware treatment |
|---|---|---|
| C-5 | Emoji in a formal column or report | Remove it. Keep useful emoji in casual product or social copy. |
| C-7 | Formulaic `먼저·반면·결국` sequence | Keep only transitions that clarify a real relation. |
| C-8 | Repeated parallel questions | Keep one useful question and state the rest directly. |
| C-9 | Decorative `(1)·(2)·(3)` indexing | Integrate it into prose. Keep functional procedures numbered. |
| C-10 | Repeated `X: Y` subtitles | Shorten decorative subtitles. Preserve navigational headings. |
| C-11 | Comma after a connective ending | Remove it unless syntax requires it. |

Do not flatten a checklist, procedure, comparison table, or reference list into prose. Structure is a problem only when it is decorative and repetitive for the genre.

## D. Canned and inflated wording

Conclusion pivots include `결론적으로`, `따라서`, `요약하면`, and `정리하면`.

| ID | Signal | Context-aware treatment |
|---|---|---|
| D-1 | Repeated conclusion pivots | Delete redundant pivots or let paragraph order show the transition. |
| D-2 | `시사하는 바가 크다/주목할 만하다` | Delete it or state the supported significance. |
| D-3 | Empty `본질적으로/핵심적으로` | Delete it. Keep it if it makes a real distinction. |
| D-4 | Repeated hype or a combined hype hedge | Use plain wording with the same stance and intensity. |
| D-5 | Personified abstraction such as `시대가 부른다` | Use the real actor when known. |
| D-6 | Formulaic ending such as `지금이야말로 ~할 때다` | End with the supported claim or action. |
| D-7 | Repeated `X에서 Y로` transformation formula | Keep the clearest one and state the rest plainly. |

Prefer deletion when a stock phrase carries no content. Do not replace it with a different stock phrase.
A combined phrase such as `매우 획기적인 변화라고 할 수 있다` can become `상당한 변화로 볼 수 있다` when that preserves the writer's judgment.

## E. Rhythm and endings

| ID | Signal | Context-aware treatment |
|---|---|---|
| E-1 | Many sentences with nearly identical length | Merge or split existing content without adding ideas. |
| E-2 | Repeated ending or `~고 있다` | Vary only where Korean usage and register support it. |
| E-7 | Mixed speech levels in one voice | Keep one level unless character or quotation differences require it. |

Natural Korean may repeat `~다` in a report. Do not force variety that sounds theatrical. Rhythm edits must come from rearranging existing material, not adding filler.

## F. Nominalization, modifiers, and duplication

| ID | Signal | Context-aware treatment |
|---|---|---|
| F-1 | Repeated `매우/정말/대단히` | Delete unsupported emphasis. Keep meaningful intensity. |
| F-2 | Doubled synonyms such as `중요하고 핵심적인` | Keep the word that matches the intended nuance. |
| F-4 | Dense `-성/-적/-화` nominalization | Restore a concrete verb, adjective, or shorter noun phrase. |
| F-5 | Abstract `~적 명사` chain | Spell out the relation or use a concrete phrase. |

Examples: `정책의 시행이 필요하다` can become `정책을 시행해야 한다`; `구조적 문제` can become `구조 자체의 문제` when that is the intended meaning.

## G. Hedging and certainty

| ID | Signal | Context-aware treatment |
|---|---|---|
| G-1 | Repeated `~것이다/~할 것이다` | Use present tense only when the source makes a current claim. |
| G-2 | Repeated `~로 보인다/~인 듯하다` | Reduce repetition without increasing certainty. |
| G-3 | Repeated safe-balance wording | Keep the actual position, including genuine balance or caution. |

Never move from possibility to certainty just to sound confident. When evidence is uncertain, vary sentence structure while retaining the same uncertainty.

## H. Connectives and meta-entry

Initial connectives include `또한`, `따라서`, `나아가`, and `아울러`. Meta-entry phrases include `이는`, `이 점에서`, `이 관점에서`, and `이 말은`.

| ID | Signal | Context-aware treatment |
|---|---|---|
| H-1 | Frequent initial connectives | Remove those made redundant by sentence order. |
| H-2 | Repeated `하지만/그러나` | Merge a contrast or vary it only when the relation remains clear. |
| H-3 | Repeated meta-entry phrases | Integrate the reference or name its subject. |
| H-4 | Repeated `즉` | Keep it only where a real restatement follows. |

## I. Formal and dependent nouns

| ID | Signal | Context-aware treatment |
|---|---|---|
| I-1 | Repeated `~인 것이다/~한 것이다` | Use a direct ending when emphasis is not needed. |
| I-2 | `X은 ~라는 점에 있다` | State the point directly. |
| I-3 | Repeated `~다는 뜻이다/~다는 의미다` | Put the meaning in the sentence itself. |
| I-4 | Repeated recommendations | Use a direct claim or action when the source supports it. |

Do not lower the formality of official writing. The target is direct formal Korean, not casual speech.

## J. Visual decoration

| ID | Signal | Context-aware treatment |
|---|---|---|
| J-1 | Excessive bold emphasis | Keep emphasis only where hierarchy or meaning requires it. |
| J-2 | Quotation marks used repeatedly for emphasis | Keep direct quotations and genuinely marked terms. |
| J-3 | Decorative bullets in a column or essay | Integrate them into prose. Keep functional lists intact. |

## Genre adjustments

| Genre | Usually allow | Usually reduce |
|---|---|---|
| Column or essay | Personal voice and existing metaphor | Decorative headings, emoji, and mechanical bullets |
| Report | Clear headings, figures, quotations, and functional lists | Hype, vague significance, and decorative emoji |
| Blog post | Friendly tone, questions, and useful lists | Repeated formulaic enumeration |
| Formal speech | Formal written register and deliberate repetition | Casual speech, emoji, and unsupported flourish |

These are defaults, not permission to change genre. Follow the user's explicit audience and format.

## Final checks

Compare the result with the source and confirm:

1. Every fact, number, name, quotation, link, and technical term is intact.
2. Negation, uncertainty, causal direction, scope, and stance did not shift.
3. Every edit fixes an identified pattern and no untouched span was polished without reason.
4. Genre, speech level, point of view, formatting semantics, and paragraph purpose remain stable.
5. The result does not add metaphor, evidence, opinion, or a stronger conclusion.
6. The prose is not over-edited. If many sentences changed, restore the least necessary edits.
