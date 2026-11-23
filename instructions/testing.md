# Test code

Apply these rules whenever you write or edit a test, in any language or framework, and whenever you specify tests
in a worker assignment. A worker assignment names, for each test it asks for, the regression that test catches.

## Whether to add a test

- Before adding a test, state in one line, in your report or the assignment, the regression it would catch that no
  existing test catches. When you cannot, do not add it.
- When an existing test already exercises the path, extend that test or add nothing, and name the test that covers
  it.
- Never write a test whose expected values are copied from the code under test, such as re-reading a schema from the
  database catalog, re-asserting constants, or repeating the implementation's steps. Assert observable behavior
  instead.
- When a change adds or alters behavior, write or update its test in the same change, not as a later follow-up.

## Test properties

- Fast: when a behavior can be checked without a container, a full application context, or the network, test it at
  that lower level. Start heavier infrastructure only when the behavior depends on the real engine.
- Independent: when a test needs state that other tests also use, such as a table, a file, a global setting, or an
  environment variable, have it create and own isolated state or use keys unique to it. Never drop, truncate,
  rename, or overwrite a shared fixture, even when a rollback would restore it.
- Repeatable: when a result can depend on time, randomness, ordering, the network, or pre-existing data, fix it
  with an injected clock, a seed, or fixtures the test creates.
- Self-validating: let assertions alone decide pass or fail, with no printed output or log reading. Let an
  unexpected exception fail the test instead of wrapping the action under test in an assertion.

## Structure

- Structure every test as given-when-then. `given` prepares state and fixtures, `when` performs exactly one
  action under test, and `then` holds only assertions. Keep the three phases visibly separated: use the
  framework's native construct when it has one, otherwise one marker line per phase.
- Write the displayed test description, such as `@DisplayName`, a `describe`/`it` title, or a runner-visible
  docstring, as a natural Korean sentence that states the expected behavior. Leave identifiers, method names,
  and literal values as they are.
- In JVM projects, build test fixtures with Instancio. When the required Instancio API is uncertain, check the
  official Instancio documentation instead of guessing. If the project does not already depend on Instancio,
  ask before adding it.
