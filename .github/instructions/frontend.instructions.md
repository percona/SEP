---
applyTo: "frontend/**"
---

# Frontend — Layout, Docs, Idiom

Layout defects in this codebase share one property: they are invisible to every gate that runs before a browser does. The diff reads correctly, the unit suite is green, and the page is broken. The rules below follow from that.

## jsdom is not layout coverage

The Vitest/jsdom environment reports **no box geometry**. Every element has zero width and height; `scrollWidth`, `clientWidth`, `getBoundingClientRect` and computed track sizes are all stubs. A jsdom test therefore cannot falsify any claim about overflow, wrapping, truncation, or visibility — it is *silent* on them, not confirming. (This is the frontend analogue of "compile-only SQL is not engine coverage": a check running at a stage where the property under test cannot fail.)

| jsdom catches | jsdom misses |
|---|---|
| Whether the text/node is present in the tree | Whether it fits, clips, wraps, or overflows |
| Which branch rendered, given props | Any computed width, height, or track size |
| Accessible name and role wiring | Whether an ellipsis actually engaged |

So a "Tested" claim about layout is unverified until measured in a real engine. The minimum assertion, at each breakpoint the change plausibly affects, is `document.documentElement.scrollWidth <= window.innerWidth`; and for anything claiming to truncate, on the element itself, `line.scrollWidth > line.clientWidth` (the ellipsis actually engaged).

## A clip depends on its ancestor chain, not on its own declarations

`whiteSpace: nowrap` + `overflow: hidden` + `textOverflow: ellipsis` is the recognised idiom for a clipped single-line label, and it is **not sufficient on its own**. Those declarations say what to do once the box is constrained; they do not constrain it.

- **`min-width: 0` does not do what it is usually reached for.** It lowers a flex item's *shrink floor*. It does **not** reduce the box's min-content *contribution* — and a `nowrap` line's min-content width is the entire string. An ancestor still at the default `min-width: auto` sizes to the full text, and the clip never engages.
- **Grid tracks have the same trap.** A bare `1fr` is `minmax(auto, 1fr)`, whose `auto` minimum is content-based. Use `minmax(0, 1fr)` for any track that must be allowed to shrink below its content.

**The rule.** When a diff introduces a clipped `nowrap` line, trace the constraint up to the nearest width-constrained ancestor. Every intervening flex item needs `min-width: 0`, and every grid track in that chain needs `minmax(0, 1fr)`. Fixing only one level does not partially work — it does not work.

Review cannot catch this by reading, because the defect lives in the *interaction* between a new declaration and the `min-width: auto` / content-based-track defaults of ancestors that are **not in the diff**, sometimes in a different file. The differential that isolates it: hide only the newly added element, change nothing else, re-measure. If `scrollWidth` drops to the viewport width, the new element is setting the page width.

**Review cue.** Does this diff add `whiteSpace: nowrap`, a long unbroken string, or a new grid track? If so — was the containment traced to a constrained ancestor, and was `scrollWidth <= innerWidth` measured in a real engine at the affected breakpoints?

## Doc comments are JSDoc, not rST

TypeScript and TSX use **JSDoc** — prose, single backticks, no rST directives. The `:param:` / `:return:` / double-backtick conventions in `python-docstrings.instructions.md` are Python-only; carried into a `.ts` file they produce doc comments no TS tooling renders. Match the nearest sibling modules in the same package.

## Component reuse

`frontend/packages/framework/src/index.ts` is the source of truth for what the framework already ships — check it before adding a parallel implementation. A barrel **re-export is not a consumer**: before claiming a component is unused, unwired, or has no React equivalent, verify against the import graph (`git grep -rn "<Component>" -- 'frontend/*'`), and treat a component whose only importers are its own test and story files as "tests/stories only", which is neither absence nor use.
