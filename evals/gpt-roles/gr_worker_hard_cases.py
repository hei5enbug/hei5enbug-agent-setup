"""Three harder worker cases of the GPT role comparison: W4 (pagination across two modules), W5 (a race in two modules), and W6
(a precedence rule that three modules each implement). Each has existing tests that pass on the seed, a requirement that only a
docstring states, hidden tests that fail a plausible shallow fix, and a cap on the source files that may change. Data only."""

from __future__ import annotations

PAGER_SOURCE = '''MAX_SIZE = 100
DEFAULT_PAGE = 1
DEFAULT_SIZE = 20


def page_slice(page, size):
    """Return the (start, stop) indexes of the 1-based `page`. A `size` above MAX_SIZE counts as MAX_SIZE and a `page` below 1 counts as page 1."""
    size = min(size, MAX_SIZE)
    start = page * size
    return start, start + size


def page_count(total, size):
    """Number of pages that hold `total` items, where a `size` above MAX_SIZE counts as MAX_SIZE. An empty listing has one page."""
    size = min(size, MAX_SIZE)
    return total // size or 1
'''

API_SOURCE = '''from shop.pager import DEFAULT_PAGE, DEFAULT_SIZE, page_count, page_slice


def _positive_int(raw, default):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def list_products(products, page=None, size=None):
    """Return one page of `products` as {"items", "page", "size", "pages", "next"}. `page` and `size` may be integers or query-string text; one that is missing, not a number, or below 1 falls back to 1 and 20. The result's `page` and `size` are the values actually used, so a `size` above 100 is reported as 100. `pages` counts all pages, and `next` is the number of the following page, or None on the last page and beyond it. A page beyond the last has no items."""
    page = _positive_int(page, DEFAULT_PAGE)
    size = _positive_int(size, DEFAULT_SIZE)
    start, stop = page_slice(page, size)
    pages = page_count(len(products), size)
    return {"items": list(products[start:stop]), "page": page, "size": size, "pages": pages, "next": page + 1 if page <= pages else None}
'''

BUCKET_SOURCE = '''import time


class TokenBucket:
    """Holds up to `capacity` tokens and gains `rate` tokens per second. Many threads may share one bucket. `take(n)` is all-or-nothing: it removes `n` tokens and returns True only when `n` tokens are available, otherwise it removes nothing and returns False. `remaining()` returns the tokens left after a refill."""

    def __init__(self, capacity, rate, clock=time.monotonic):
        self.capacity = capacity
        self.rate = rate
        self._clock = clock
        self._tokens = float(capacity)
        self._stamp = clock()

    def _refill(self):
        tokens, stamp = self._tokens, self._stamp
        now = self._clock()
        self._tokens = min(self.capacity, tokens + (now - stamp) * self.rate)
        self._stamp = now

    def take(self, n=1):
        self._refill()
        if self._tokens < n:
            return False
        self._tokens -= n
        return True

    def remaining(self):
        self._refill()
        return self._tokens
'''

LIMITER_SOURCE = '''class Limiter:
    """Keeps one bucket per key, made on first use by calling `factory()`. Many threads may call `allow` and `stats` at once, and `factory` runs exactly once per key. `allow(key, n)` takes `n` tokens from the key's bucket. `stats()` returns {key: remaining tokens} for every key made so far."""

    def __init__(self, factory):
        self._factory = factory
        self._buckets = {}

    def bucket(self, key):
        if key not in self._buckets:
            self._buckets[key] = self._factory()
        return self._buckets[key]

    def allow(self, key, n=1):
        return self.bucket(key).take(n)

    def stats(self):
        return {key: bucket.remaining() for key, bucket in self._buckets.items()}
'''

DEFAULTS_SOURCE = '''DEFAULTS = {"port": 8080, "timeout": 30, "debug": True, "name": "app"}
'''

SETTINGS_SOURCE = '''from config.defaults import DEFAULTS

ENV_PREFIX = "APP_"


def parse_env(name, raw):
    default = DEFAULTS[name]
    if isinstance(default, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        return int(raw)
    return raw


def get_setting(name, file_values, env, cli=None):
    """Value of setting `name`. Precedence: a command line value, then the environment variable APP_<NAME>, then the config file value, then the default. A command line or file value of 0, False, or an empty string is a real value, and a command line value of None means not given. An environment variable set to an empty string counts as unset; any other text is parsed to the type of the default, so "0" gives 0 and "false" gives False."""
    cli_value = (cli or {}).get(name)
    if cli_value:
        return cli_value
    raw = env.get(ENV_PREFIX + name.upper())
    if raw:
        return parse_env(name, raw)
    if file_values.get(name):
        return file_values[name]
    return DEFAULTS[name]
'''

CLI_SOURCE_W6 = '''from config.defaults import DEFAULTS
from config.settings import ENV_PREFIX, parse_env


def describe(file_values, env, cli=None):
    """One line per setting, sorted by name, as "name=value (source)" where source is cli, env, file, or default. It follows the same precedence as get_setting."""
    lines = []
    for name in sorted(DEFAULTS):
        raw = env.get(ENV_PREFIX + name.upper())
        if (cli or {}).get(name):
            value, source = cli[name], "cli"
        elif raw:
            value, source = parse_env(name, raw), "env"
        elif file_values.get(name):
            value, source = file_values[name], "file"
        else:
            value, source = DEFAULTS[name], "default"
        lines.append(f"{name}={value} ({source})")
    return lines
'''

EXPORT_SOURCE = '''from config.defaults import DEFAULTS
from config.settings import ENV_PREFIX


def to_env_lines(file_values, cli=None):
    """One APP_<NAME>=value line per setting, sorted by name, from the command line value, then the config file value, then the default; the environment is not read. A bool is written as true or false."""
    lines = []
    for name in sorted(DEFAULTS):
        value = (cli or {}).get(name) or file_values.get(name) or DEFAULTS[name]
        if isinstance(value, bool):
            value = str(value).lower()
        lines.append(f"{ENV_PREFIX}{name.upper()}={value}")
    return lines
'''

HIDDEN_W4 = '''from shop.api import list_products
from shop.pager import page_count, page_slice

ITEMS = list(range(45))


def test_pages_follow_one_based_numbers():
    assert list_products(ITEMS, 1, 20)["items"] == ITEMS[:20]
    assert list_products(ITEMS, 2, 20)["items"] == ITEMS[20:40]


def test_partial_last_page_is_reachable():
    last = list_products(ITEMS, 3, 20)
    assert last["items"] == ITEMS[40:]
    assert last["pages"] == 3
    assert last["next"] is None
    assert list_products(ITEMS, 2, 20)["next"] == 3


def test_page_beyond_the_last_is_empty():
    beyond = list_products(ITEMS, 4, 20)
    assert beyond["items"] == [] and beyond["next"] is None and beyond["page"] == 4


def test_exact_multiple_and_empty_listing():
    full = list_products(list(range(40)), 2, 20)
    assert full["pages"] == 2 and full["next"] is None
    empty = list_products([], 1, 20)
    assert empty["items"] == [] and empty["pages"] == 1 and empty["next"] is None


def test_oversized_size_is_clamped_and_reported():
    result = list_products(list(range(250)), 2, 500)
    assert result["size"] == 100
    assert result["items"] == list(range(100, 200))
    assert result["pages"] == 3 and result["next"] == 3


def test_query_strings_and_fallbacks():
    assert list_products(ITEMS, "2", "10")["items"] == ITEMS[10:20]
    fallback = list_products(ITEMS, "0", "-4")
    assert fallback["page"] == 1 and fallback["size"] == 20 and fallback["items"] == ITEMS[:20]
    junk = list_products(ITEMS, "x", "0")
    assert junk["page"] == 1 and junk["size"] == 20


def test_pager_functions_on_their_own():
    assert page_slice(1, 10) == (0, 10)
    assert page_slice(3, 10) == (20, 30)
    assert page_slice(0, 10) == (0, 10)
    assert page_slice(-2, 10) == (0, 10)
    assert page_slice(2, 500) == (100, 200)
    assert page_count(25, 10) == 3
    assert page_count(20, 10) == 2
    assert page_count(0, 10) == 1
    assert page_count(250, 500) == 3
    assert page_count(101, 100) == 2
'''

HIDDEN_W5 = '''import threading
import time

from ratelimit.bucket import TokenBucket
from ratelimit.limiter import Limiter


def slow_clock():
    time.sleep(0.01)
    return 0.0


def run_threads(targets):
    threads = [threading.Thread(target=target, daemon=True) for target in targets]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads), "a thread did not finish"


def test_shared_bucket_never_gives_out_more_than_its_capacity():
    bucket = TokenBucket(10, 0, clock=slow_clock)
    results = []
    run_threads([lambda: results.append(bucket.take(1)) for _ in range(40)])
    assert results.count(True) == 10


def test_remaining_does_not_disturb_concurrent_takes():
    bucket = TokenBucket(10, 0, clock=slow_clock)
    results = []
    targets = [lambda: results.append(bucket.take(1)) for _ in range(20)] + [bucket.remaining for _ in range(20)]
    run_threads(targets)
    assert results.count(True) == 10
    assert bucket.remaining() == 0


def test_factory_runs_once_per_key_under_concurrency():
    made = []

    def factory():
        made.append(1)
        time.sleep(0.01)
        return TokenBucket(10, 0, clock=lambda: 0.0)

    limiter = Limiter(factory)
    results = []
    run_threads([lambda: results.append(limiter.allow("a")) for _ in range(40)])
    assert len(made) == 1
    assert results.count(True) == 10


def test_stats_while_keys_are_being_added():
    limiter = Limiter(lambda: TokenBucket(5, 0, clock=slow_clock))
    errors = []
    done = threading.Event()

    def add(start):
        for index in range(start, start + 15):
            limiter.allow(f"k{index}")

    def watch():
        while not done.is_set():
            try:
                limiter.stats()
            except RuntimeError as error:
                errors.append(error)

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    run_threads([lambda start=start: add(start) for start in range(0, 60, 15)])
    done.set()
    watcher.join(timeout=30)
    assert errors == []
    assert len(limiter.stats()) == 60
'''

HIDDEN_W6 = '''import itertools

from config.cli import describe
from config.export import to_env_lines
from config.settings import get_setting


def test_zero_false_and_empty_values_are_real_in_every_function():
    file_values = {"timeout": 0, "debug": False, "name": ""}
    assert get_setting("timeout", file_values, {}) == 0
    assert get_setting("debug", file_values, {}) is False
    assert get_setting("name", file_values, {}) == ""
    assert describe(file_values, {}) == ["debug=False (file)", "name= (file)", "port=8080 (default)", "timeout=0 (file)"]
    assert to_env_lines(file_values) == ["APP_DEBUG=false", "APP_NAME=", "APP_PORT=8080", "APP_TIMEOUT=0"]


def test_command_line_zero_beats_environment_and_file():
    env, file_values, cli = {"APP_TIMEOUT": "5"}, {"timeout": 9}, {"timeout": 0, "debug": False}
    assert get_setting("timeout", file_values, env, cli) == 0
    assert get_setting("debug", {}, {"APP_DEBUG": "true"}, cli) is False
    assert "timeout=0 (cli)" in describe(file_values, env, cli)
    assert "APP_TIMEOUT=0" in to_env_lines(file_values, cli)


def test_none_on_the_command_line_means_not_given():
    cli = {"timeout": None}
    assert get_setting("timeout", {"timeout": 9}, {}, cli) == 9
    assert "timeout=9 (file)" in describe({"timeout": 9}, {}, cli)
    assert "APP_TIMEOUT=9" in to_env_lines({"timeout": 9}, cli)


def test_environment_text_is_parsed_and_empty_text_is_unset():
    assert get_setting("timeout", {"timeout": 9}, {"APP_TIMEOUT": "0"}) == 0
    assert get_setting("debug", {}, {"APP_DEBUG": "false"}) is False
    assert get_setting("timeout", {"timeout": 9}, {"APP_TIMEOUT": ""}) == 9
    assert get_setting("timeout", {}, {"APP_TIMEOUT": ""}) == 30
    lines = describe({"timeout": 9}, {"APP_TIMEOUT": "0", "APP_PORT": ""})
    assert "timeout=0 (env)" in lines and "port=8080 (default)" in lines


def test_describe_agrees_with_get_setting_for_every_combination():
    cli_options = [None, {"timeout": 0}, {"timeout": 4}, {"timeout": None}]
    file_options = [{}, {"timeout": 0}, {"timeout": 9}]
    env_options = [{}, {"APP_TIMEOUT": ""}, {"APP_TIMEOUT": "0"}, {"APP_TIMEOUT": "6"}]
    for cli, file_values, env in itertools.product(cli_options, file_options, env_options):
        value = get_setting("timeout", file_values, env, cli)
        line = next(item for item in describe(file_values, env, cli) if item.startswith("timeout="))
        assert line.startswith(f"timeout={value} ("), (cli, file_values, env, line)
'''

CASES = {
    "W4": {
        "title": "Fix pagination that is off by one across the pager and the API",
        "files": {
            "shop/__init__.py": "", "shop/pager.py": PAGER_SOURCE, "shop/api.py": API_SOURCE,
            "tests/test_pager.py": (
                "from shop.pager import page_count\n\n\ndef test_exact_multiple_has_no_extra_page():\n    assert page_count(20, 10) == 2\n\n\n"
                "def test_empty_listing_has_one_page():\n    assert page_count(0, 10) == 1\n"),
            "tests/test_api.py": (
                "from shop.api import list_products\n\n\ndef test_empty_listing():\n    assert list_products([], 1, 10)[\"items\"] == []\n\n\n"
                "def test_text_that_is_not_a_number_falls_back():\n    result = list_products(list(range(30)), \"abc\", \"x\")\n"
                "    assert (result[\"page\"], result[\"size\"]) == (1, 20)\n"),
        },
        "assignment": (
            "Page 1 of the product listing returns the items of page 2, and the last partial page cannot be reached. Fix shop/pager.py and "
            "shop/api.py so that every function follows its docstring. Keep the public function names, arguments, and return shapes. Edit only "
            "shop/pager.py, shop/api.py, and the tests folder, and change at most two files outside tests/. Run the tests, make no commit, and "
            "report the changed paths and the test result.\n"),
        "allowed": ("shop/pager.py", "shop/api.py", "tests/"),
        "max_source_files": 2,
        "hidden": {"tests_hidden/test_pagination.py": HIDDEN_W4},
    },
    "W5": {
        "title": "Make the shared token bucket and the limiter safe under threads",
        "files": {
            "ratelimit/__init__.py": "", "ratelimit/bucket.py": BUCKET_SOURCE, "ratelimit/limiter.py": LIMITER_SOURCE,
            "tests/test_bucket.py": (
                "from ratelimit.bucket import TokenBucket\n\n\ndef test_take_is_all_or_nothing():\n    bucket = TokenBucket(3, 0, clock=lambda: 0.0)\n"
                "    assert bucket.take(2) is True\n    assert bucket.take(2) is False\n    assert bucket.remaining() == 1\n\n\n"
                "def test_refill_is_capped():\n    now = [0.0]\n    bucket = TokenBucket(3, 1, clock=lambda: now[0])\n    bucket.take(3)\n"
                "    now[0] = 10.0\n    assert bucket.remaining() == 3\n"),
            "tests/test_limiter.py": (
                "from ratelimit.bucket import TokenBucket\nfrom ratelimit.limiter import Limiter\n\n\n"
                "def test_one_bucket_per_key():\n    limiter = Limiter(lambda: TokenBucket(1, 0, clock=lambda: 0.0))\n"
                "    assert limiter.allow('a') is True\n    assert limiter.allow('a') is False\n    assert limiter.allow('b') is True\n"
                "    assert limiter.stats() == {'a': 0, 'b': 0}\n"),
        },
        "assignment": (
            "Under load the limiter admits more calls than a bucket's capacity, and `stats()` sometimes raises. Make `TokenBucket` and `Limiter` "
            "behave as their docstrings promise when many threads use them at once. Keep the public names, arguments, and return values. Edit "
            "only ratelimit/bucket.py, ratelimit/limiter.py, and the tests folder, and change at most two files outside tests/. Run the tests, "
            "make no commit, and report the changed paths and the test result.\n"),
        "allowed": ("ratelimit/bucket.py", "ratelimit/limiter.py", "tests/"),
        "max_source_files": 2,
        "hidden": {"tests_hidden/test_threads.py": HIDDEN_W5},
    },
    "W6": {
        "title": "Make falsy settings win in every function of the config package",
        "files": {
            "config/__init__.py": "", "config/defaults.py": DEFAULTS_SOURCE, "config/settings.py": SETTINGS_SOURCE,
            "config/cli.py": CLI_SOURCE_W6, "config/export.py": EXPORT_SOURCE,
            "tests/test_config.py": (
                "from config.cli import describe\nfrom config.export import to_env_lines\nfrom config.settings import get_setting\n\n\n"
                "def test_default_file_and_env():\n    assert get_setting('port', {}, {}) == 8080\n    assert get_setting('port', {'port': 9000}, {}) == 9000\n"
                "    assert get_setting('port', {'port': 9000}, {'APP_PORT': '9090'}) == 9090\n\n\n"
                "def test_empty_environment_text_is_unset():\n    assert get_setting('timeout', {'timeout': 7}, {'APP_TIMEOUT': ''}) == 7\n\n\n"
                "def test_describe_format():\n    assert describe({'port': 9000}, {}) == ['debug=True (default)', 'name=app (default)', 'port=9000 (file)', 'timeout=30 (default)']\n\n\n"
                "def test_export_format():\n    assert to_env_lines({'debug': True}) == ['APP_DEBUG=true', 'APP_NAME=app', 'APP_PORT=8080', 'APP_TIMEOUT=30']\n"),
        },
        "assignment": (
            "A `timeout` of 0 in the config file is ignored: `get_setting` returns the default 30. Fix it so that every public function of the "
            "config package follows the precedence its docstring states, and keep every signature and output format. Edit only the config "
            "folder and the tests folder, change at most three files outside tests/, and add no new module. Run the tests, make no commit, and "
            "report the changed paths and the test result.\n"),
        "allowed": ("config/", "tests/"),
        "max_source_files": 3,
        "no_new_files": True,
        "hidden": {"tests_hidden/test_precedence.py": HIDDEN_W6},
    },
}
