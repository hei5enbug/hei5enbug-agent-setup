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


CEIL = "    return max(1, -(-total // size))\n"
PAGER_FIXED = swap(hard.PAGER_SOURCE, "    return total // size or 1\n", CEIL)
PAGER_ONE_BASED = pager("    start = (page - 1) * size\n", CEIL)
PAGER_PLUS_ONE = swap(hard.PAGER_SOURCE, "    return total // size or 1\n", "    return total // size + 1\n")
API_CLAMPED = swap(swap(swap(hard.API_SOURCE, "import DEFAULT_PAGE, DEFAULT_SIZE, page_count", "import DEFAULT_PAGE, DEFAULT_SIZE, MAX_SIZE, page_count"),
                        "    size = _positive_int(size, DEFAULT_SIZE)\n", "    size = min(_positive_int(size, DEFAULT_SIZE), MAX_SIZE)\n"),
                   "if page <= pages else None", "if page < pages else None")
API_FIXED = swap(API_CLAMPED, "page_slice(page, size)", "page_slice(page - 1, size)")
API_PAGE_ONLY = swap(hard.API_SOURCE, "page_slice(page, size)", "page_slice(page - 1, size)")
EXPORT_COMPENSATED = swap(hard.EXPORT_SOURCE_W4, "page_slice(page, size)", "page_slice(page + 1, size)")

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
LIMITER_PLAIN_LOCK = swap(LIMITER_BUCKET_LOCKED, "        return {key: bucket.remaining() for key, bucket in self._buckets.items()}\n",
                     "        with self._lock:\n            items = list(self._buckets.items())\n        return {key: bucket.remaining() for key, bucket in items}\n")
LIMITER_FIXED = LIMITER_PLAIN_LOCK.replace("threading.Lock()", "threading.RLock()")
METRICS_LOCKED = swap(swap(swap(hard.METRICS_SOURCE, "class Counter", "import threading\n\n\nclass Counter"),
                           "        self.count = 0\n", "        self.count = 0\n        self._lock = threading.Lock()\n"),
                      "        self.count += 1\n", "        with self._lock:\n            self.count += 1\n")
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

DIFF_FIXED = '''from config.defaults import DEFAULTS
from config.settings import resolve


def sources(file_values, env, cli=None):
    """{name: source} for every setting, where source is cli, env, file, or default. It follows the same precedence as get_setting."""
    return {name: resolve(name, file_values, env, cli)[1] for name in DEFAULTS}
'''
DIFF_VIA_MODULE = DIFF_FIXED.replace("from config.settings import resolve", "from config.resolve import resolve")

SOLUTIONS = {
    "W4": {"shop/pager.py": PAGER_FIXED, "shop/api.py": API_FIXED},
    "W5": {"ratelimit/bucket.py": BUCKET_FIXED, "ratelimit/limiter.py": LIMITER_FIXED},
    "W6": {"config/settings.py": SETTINGS_FIXED, "config/cli.py": CLI_FIXED, "config/export.py": EXPORT_FIXED, "config/diff.py": DIFF_FIXED},
}
# Each shallow fix is a plausible reading of the assignment that stops early. The note names the requirement it misses.
SHALLOW = {
    "W4": {
        "pager made one-based": ({"shop/pager.py": PAGER_ONE_BASED, "shop/api.py": API_CLAMPED}, "export and the pager's own contract count from 0"),
        "pager one-based and export compensated": ({"shop/pager.py": PAGER_ONE_BASED, "shop/api.py": API_CLAMPED, "shop/export.py": EXPORT_COMPENSATED},
                                                   "the pager's documented zero-based contract changed"),
        "api shift only": ({"shop/api.py": API_PAGE_ONLY}, "page count, reported size, and next page stay wrong"),
        "ceiling written as floor plus one": ({"shop/pager.py": PAGER_PLUS_ONE, "shop/api.py": API_FIXED}, "an exact multiple gets an extra page"),
    },
    "W5": {
        "lock in take and a setdefault": ({"ratelimit/bucket.py": LOCKED_TAKE, "ratelimit/limiter.py": LIMITER_SETDEFAULT}, "factory runs more than once and remaining is unlocked"),
        "lock only in the limiter": ({"ratelimit/limiter.py": LIMITER_ALLOW_LOCKED}, "a bucket shared on its own is still unsafe, and a factory reading the limiter deadlocks"),
        "locks everywhere except stats": ({"ratelimit/bucket.py": BUCKET_FIXED, "ratelimit/limiter.py": LIMITER_BUCKET_LOCKED}, "stats iterates the dict while keys are added"),
        "plain lock around the factory": ({"ratelimit/bucket.py": BUCKET_FIXED, "ratelimit/limiter.py": LIMITER_PLAIN_LOCK}, "a factory that reads the limiter deadlocks"),
        "also a lock in the single-thread counter": ({"ratelimit/bucket.py": BUCKET_FIXED, "ratelimit/limiter.py": LIMITER_FIXED, "ratelimit/metrics.py": METRICS_LOCKED},
                                                     "a file that must stay as it is changed"),
    },
    "W6": {
        "get_setting only": ({"config/settings.py": SETTINGS_IN_PLACE}, "describe, to_env_lines, and sources keep ignoring falsy values"),
        "is not None for every source": ({"config/settings.py": SETTINGS_ENV_TOO, "config/cli.py": CLI_IN_PLACE}, "an empty environment text must count as unset"),
        "every resolver except sources": ({"config/settings.py": SETTINGS_FIXED, "config/cli.py": CLI_FIXED, "config/export.py": EXPORT_FIXED}, "sources keeps ignoring falsy values"),
        "shared helper in a new module": ({"config/resolve.py": RESOLVE_MODULE, "config/settings.py": SETTINGS_VIA_MODULE, "config/cli.py": CLI_VIA_MODULE,
                                           "config/export.py": EXPORT_VIA_MODULE, "config/diff.py": DIFF_VIA_MODULE}, "adds a module and changes five files"),
        "falsy values accepted by validation": ({"config/settings.py": SETTINGS_FIXED, "config/cli.py": CLI_FIXED, "config/export.py": EXPORT_FIXED, "config/diff.py": DIFF_FIXED,
                                                 "config/validate.py": "def check(file_values):\n    return None\n"}, "validation of 0 must stay and a fifth file changed"),
    },
}
