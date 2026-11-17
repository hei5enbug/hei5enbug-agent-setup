# Repository rules

- Python 3.11 or newer, standard library only. Do not add a dependency.
- Run `python3 -m pytest -q` before reporting a change as done.
- Settings live in `config/settings.toml`. Code reads them through `orders.settings`.
- Money is whole cents everywhere. Only `orders.money` turns cents into text.
- User-visible changes to the commands are described in `README.md`.

## Commits

- Use Conventional Commits: `<type>: <description>`. Write the message in English, in the imperative mood, with a
  subject of at most 72 characters and no trailers.
