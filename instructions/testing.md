# Test code

Apply these rules whenever you write or edit a test, in any language or framework.

- Structure every test as given-when-then. `given` prepares state and fixtures, `when` performs exactly one
  action under test, and `then` holds only assertions. Keep the three phases visibly separated: use the
  framework's native construct when it has one, otherwise one marker line per phase.
- Write the displayed test description, such as `@DisplayName`, a `describe`/`it` title, or a runner-visible
  docstring, as a natural Korean sentence that states the expected behavior. Leave identifiers, method names,
  and literal values as they are.
- In JVM projects, build test fixtures with Instancio. When the required Instancio API is uncertain, check the
  official Instancio documentation instead of guessing. If the project does not already depend on Instancio,
  ask before adding it.
