# Logic prototype

Build a small interactive terminal program when the question concerns business logic, state
transitions, or data shape.

## Process

1. Write the question at the top of the prototype or in a nearby README.
2. Use the repository's existing language and task runner.
3. Put the decision logic behind a small pure interface:
   - a reducer for discrete actions;
   - a state machine when legal actions depend on current state;
   - pure functions for stateless transformations;
   - a small module when ongoing internal state is essential.
4. Keep terminal input and rendering outside that interface.
5. Render the full current state and available actions after every input.
6. Keep the entire interface on one terminal screen when practical.
7. Provide one command to start it.

Do not add tests, connect a real database, generalize beyond the question, or ship the terminal
shell as production code. The validated pure logic may later inform the real implementation.
