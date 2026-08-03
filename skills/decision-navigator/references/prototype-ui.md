# UI prototype

Create several structurally different UI variants when the question concerns layout, information
hierarchy, or visual interaction.

## Placement

Prefer mounting variants inside an existing page so they use real navigation, data density, and
surrounding layout. Create a throwaway route only when no existing page is a sensible host.

## Process

1. State the question and default to three variants. Never exceed five.
2. Make variants disagree about structure and primary affordance, not only color or wording.
3. Reuse the project's component and styling systems.
4. Select a variant with a shareable URL parameter such as `?variant=A`.
5. Add a small fixed switcher with previous, current, and next controls.
6. Support left and right arrow keys unless a text input is focused.
7. Ensure the switcher cannot appear in a production build.
8. Give the human the URL and wait for comparative feedback.

After a choice is made, record the winner and the useful parts of rejected variants. Remove the
switcher and losing variants from the main line. Prototype code lacks production tests and error
handling, so rewrite or harden the chosen idea before shipping it.
