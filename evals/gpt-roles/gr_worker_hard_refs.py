"""Reference solutions and typical shallow fixes of the hard worker cases W4 to W6, as {relative path: full text} maps. They are never
seeded into a run: tests/test_gpt_roles_hard.py applies them to prove the reference passes and every shallow fix fails."""

from __future__ import annotations

import gr_worker_hard_cases as hard


def swap(text: str, old: str, new: str) -> str:
    """Replace one exact fragment and fail loudly when the fragment is absent."""
    if old not in text:
        raise ValueError(f"fragment not found: {old[:60]}")
    return text.replace(old, new, 1)


def pager(start: str, count: str) -> str:
    text = swap(hard.PAGER_SOURCE, "    start = page * size\n", start)
    return swap(text, "    return total // size or 1\n", count)


PAGER_FIXED = pager("    start = (max(page, 1) - 1) * size\n", "    return max(1, -(-total // size))\n")
PAGER_NO_CLAMP = pager("    start = (page - 1) * size\n", "    return max(1, -(-total // size))\n")
PAGER_PLUS_ONE = pager("    start = (max(page, 1) - 1) * size\n", "    return total // size + 1\n")
API_FIXED = swap(swap(hard.API_SOURCE, "import DEFAULT_PAGE, DEFAULT_SIZE, page_count", "import DEFAULT_PAGE, DEFAULT_SIZE, MAX_SIZE, page_count"),
                 "    size = _positive_int(size, DEFAULT_SIZE)\n", "    size = min(_positive_int(size, DEFAULT_SIZE), MAX_SIZE)\n")
API_FIXED = swap(API_FIXED, "if page <= pages else None", "if page < pages else None")
API_NEXT_ONLY = swap(hard.API_SOURCE, "if page <= pages else None", "if page < pages else None")
API_INLINE = swap(swap(API_FIXED, "    start, stop = page_slice(page, size)\n    pages = page_count(len(products), size)\n",
                       "    start, stop = (page - 1) * size, page * size\n    pages = max(1, -(-len(products) // size))\n"),
                  "from shop.pager import DEFAULT_PAGE, DEFAULT_SIZE, MAX_SIZE, page_count, page_slice", "from shop.pager import DEFAULT_PAGE, DEFAULT_SIZE, MAX_SIZE")

LOCKED_TAKE = swap(swap(swap(hard.BUCKET_SOURCE, "import time\n", "import threading\nimport time\n"),
                        "        self._stamp = clock()\n", "        self._stamp = clock()\n        self._lock = threading.Lock()\n"),
                   "    def take(self, n=1):\n        self._refill()\n        if self._tokens < n:\n            return False\n        self._tokens -= n\n        return True\n",
                   "    def take(self, n=1):\n        with self._lock:\n            self._refill()\n            if self._tokens < n:\n                return False\n            self._tokens -= n\n            return True\n")
BUCKET_FIXED = swap(LOCKED_TAKE, "    def remaining(self):\n        self._refill()\n        return self._tokens\n",
                    "    def remaining(self):\n        with self._lock:\n            self._refill()\n            return self._tokens\n")
LIMITER_LOCK_IMPORT = "import threading\n\n\n" + hard.LIMITER_SOURCE
LIMITER_WITH_LOCK = swap(LIMITER_LOCK_IMPORT, "        self._buckets = {}\n", "        self._buckets = {}\n        self._lock = threading.Lock()\n")
LIMITER_BUCKET_LOCKED = swap(LIMITER_WITH_LOCK,
                             "        if key not in self._buckets:\n            self._buckets[key] = self._factory()\n        return self._buckets[key]\n",
                             "        with self._lock:\n            if key not in self._buckets:\n                self._buckets[key] = self._factory()\n            return self._buckets[key]\n")
LIMITER_FIXED = swap(LIMITER_BUCKET_LOCKED, "        return {key: bucket.remaining() for key, bucket in self._buckets.items()}\n",
                     "        with self._lock:\n            items = list(self._buckets.items())\n        return {key: bucket.remaining() for key, bucket in items}\n")
LIMITER_SETDEFAULT = swap(hard.LIMITER_SOURCE, "        if key not in self._buckets:\n            self._buckets[key] = self._factory()\n        return self._buckets[key]\n",
                          "        return self._buckets.setdefault(key, self._factory())\n")
LIMITER_ALLOW_LOCKED = swap(swap(LIMITER_WITH_LOCK, "    def allow(self, key, n=1):\n        return self.bucket(key).take(n)\n",
                                 "    def allow(self, key, n=1):\n        with self._lock:\n            return self.bucket(key).take(n)\n"),
                            "        return {key: bucket.remaining() for key, bucket in self._buckets.items()}\n",
                            "        with self._lock:\n            return {key: bucket.remaining() for key, bucket in self._buckets.items()}\n")

RESOLVE = '''

def resolve(name, file_values, env, cli=None):
    """Return (value, source) of setting `name`, where source is cli, env, file, or default."""
    cli_value = (cli or {}).get(name)
    if cli_value is not None:
        return cli_value, "cli"
    raw = env.get(ENV_PREFIX + name.upper())
    if raw:
        return parse_env(name, raw), "env"
    if file_values.get(name) is not None:
        return file_values[name], "file"
    return DEFAULTS[name], "default"
'''
GET_START = "def get_setting("


def settings_text(body: str) -> str:
    head = hard.SETTINGS_SOURCE[: hard.SETTINGS_SOURCE.index(GET_START)].rstrip("\n") + "\n"
    doc = hard.SETTINGS_SOURCE.split('"""')[1]
    return head + RESOLVE + f'\n\ndef get_setting(name, file_values, env, cli=None):\n    """{doc}"""\n{body}'


SETTINGS_FIXED = settings_text("    return resolve(name, file_values, env, cli)[0]\n")
SETTINGS_IN_PLACE = swap(swap(hard.SETTINGS_SOURCE, "    if cli_value:\n", "    if cli_value is not None:\n"),
                         "    if file_values.get(name):\n", "    if file_values.get(name) is not None:\n")
SETTINGS_ENV_TOO = swap(SETTINGS_IN_PLACE, "    if raw:\n", "    if raw is not None:\n")
CLI_FIXED = '''from config.defaults import DEFAULTS
from config.settings import resolve


def describe(file_values, env, cli=None):
    """One line per setting, sorted by name, as "name=value (source)" where source is cli, env, file, or default. It follows the same precedence as get_setting."""
    lines = []
    for name in sorted(DEFAULTS):
        value, source = resolve(name, file_values, env, cli)
        lines.append(f"{name}={value} ({source})")
    return lines
'''
CLI_IN_PLACE = swap(swap(hard.CLI_SOURCE_W6, "        if (cli or {}).get(name):\n", "        if (cli or {}).get(name) is not None:\n"),
                    "        elif file_values.get(name):\n", "        elif file_values.get(name) is not None:\n")
EXPORT_FIXED = swap(swap(hard.EXPORT_SOURCE, "from config.settings import ENV_PREFIX\n", "from config.settings import ENV_PREFIX, resolve\n"),
                    "        value = (cli or {}).get(name) or file_values.get(name) or DEFAULTS[name]\n", "        value, _ = resolve(name, file_values, {}, cli)\n")

RESOLVE_MODULE = ("from config.defaults import DEFAULTS\n\n" + hard.SETTINGS_SOURCE[hard.SETTINGS_SOURCE.index("ENV_PREFIX"):hard.SETTINGS_SOURCE.index("\n\ndef get_setting(")] + RESOLVE)
SETTINGS_VIA_MODULE = ("from config.resolve import ENV_PREFIX, parse_env, resolve  # noqa: F401\n\n\ndef get_setting(name, file_values, env, cli=None):\n    \"\"\"Value of setting `name`; see resolve.\"\"\"\n"
                       "    return resolve(name, file_values, env, cli)[0]\n")
CLI_VIA_MODULE = CLI_FIXED.replace("from config.settings import resolve", "from config.resolve import resolve")
EXPORT_VIA_MODULE = EXPORT_FIXED.replace("from config.settings import ENV_PREFIX, resolve", "from config.resolve import ENV_PREFIX, resolve")

SOLUTIONS = {
    "W4": {"shop/pager.py": PAGER_FIXED, "shop/api.py": API_FIXED},
    "W5": {"ratelimit/bucket.py": BUCKET_FIXED, "ratelimit/limiter.py": LIMITER_FIXED},
    "W6": {"config/settings.py": SETTINGS_FIXED, "config/cli.py": CLI_FIXED, "config/export.py": EXPORT_FIXED},
}
# Each shallow fix is a plausible reading of the assignment that stops early. The note names the requirement it misses.
SHALLOW = {
    "W4": {
        "pager only": ({"shop/pager.py": PAGER_NO_CLAMP}, "api still echoes an oversized size and reports a next page on the last page"),
        "api only": ({"shop/api.py": API_INLINE}, "pager functions stay wrong when called on their own"),
        "ceiling written as floor plus one": ({"shop/pager.py": PAGER_PLUS_ONE, "shop/api.py": API_FIXED}, "an exact multiple gets an extra page"),
        "pager and the next page only": ({"shop/pager.py": PAGER_FIXED, "shop/api.py": API_NEXT_ONLY}, "an oversized size is still reported as asked"),
    },
    "W5": {
        "lock in take and a setdefault": ({"ratelimit/bucket.py": LOCKED_TAKE, "ratelimit/limiter.py": LIMITER_SETDEFAULT}, "factory runs more than once and remaining is unlocked"),
        "lock only in the limiter": ({"ratelimit/limiter.py": LIMITER_ALLOW_LOCKED}, "a bucket shared on its own is still unsafe"),
        "locks everywhere except stats": ({"ratelimit/bucket.py": BUCKET_FIXED, "ratelimit/limiter.py": LIMITER_BUCKET_LOCKED}, "stats iterates the dict while keys are added"),
    },
    "W6": {
        "get_setting only": ({"config/settings.py": SETTINGS_IN_PLACE}, "describe and to_env_lines keep ignoring falsy values"),
        "is not None for every source": ({"config/settings.py": SETTINGS_ENV_TOO, "config/cli.py": CLI_IN_PLACE}, "an empty environment text must count as unset"),
        "settings and describe only": ({"config/settings.py": SETTINGS_IN_PLACE, "config/cli.py": CLI_IN_PLACE}, "to_env_lines keeps ignoring falsy values"),
        "shared helper in a new module": ({"config/resolve.py": RESOLVE_MODULE, "config/settings.py": SETTINGS_VIA_MODULE, "config/cli.py": CLI_VIA_MODULE,
                                           "config/export.py": EXPORT_VIA_MODULE}, "adds a module and changes four files"),
    },
}
