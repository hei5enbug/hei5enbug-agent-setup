import sys

from patch_tools import replace

repo = sys.argv[1]

replace(repo, "inventory/errors.py", "class StorageError(InventoryError):", '''class LockTimeout(InventoryError):
    def __init__(self, path: object, seconds: float) -> None:
        super().__init__(f"could not lock {path} within {seconds:g} seconds: another inventory command is writing it")
        self.path = path
        self.seconds = seconds


class StorageError(InventoryError):''')

replace(repo, "inventory/config.py", "import os\nfrom dataclasses", "import math\nimport os\nfrom dataclasses")
replace(repo, "inventory/config.py", 'DEFAULT_TAX_RATE = Decimal("0.08")\n', 'DEFAULT_TAX_RATE = Decimal("0.08")\nDEFAULT_LOCK_TIMEOUT = 10.0\n')
replace(repo, "inventory/config.py", "    tax_rate: Decimal = DEFAULT_TAX_RATE\n", "    tax_rate: Decimal = DEFAULT_TAX_RATE\n    lock_timeout: float = DEFAULT_LOCK_TIMEOUT\n")
replace(repo, "inventory/config.py", '            tax_rate=_read_rate(env.get("INVENTORY_TAX_RATE"), DEFAULT_TAX_RATE),\n',
        '            tax_rate=_read_rate(env.get("INVENTORY_TAX_RATE"), DEFAULT_TAX_RATE),\n            lock_timeout=_read_timeout(env.get("INVENTORY_LOCK_TIMEOUT")),\n')
replace(repo, "inventory/config.py", "def _read_currency(", '''def _read_timeout(raw: str | None) -> float:
    if raw is None or not raw.strip():
        return DEFAULT_LOCK_TIMEOUT
    try:
        seconds = float(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"INVENTORY_LOCK_TIMEOUT must be a number of seconds, got {raw!r}") from exc
    if not math.isfinite(seconds) or seconds < 0:
        raise ConfigError(f"INVENTORY_LOCK_TIMEOUT must be a finite number of seconds, 0 or more, got {raw!r}")
    return seconds


def _read_currency(''')

replace(repo, "inventory/app.py", "from dataclasses import dataclass\nfrom pathlib import Path\n",
        "import fcntl\nimport time\nfrom contextlib import contextmanager\nfrom dataclasses import dataclass\nfrom pathlib import Path\nfrom typing import IO, Iterator\n")
replace(repo, "inventory/app.py", "from .config import Config\n", "from .config import Config\nfrom .errors import LockTimeout\n")
replace(repo, "inventory/app.py", "from .items import CatalogService\n", "from .items import CatalogService\n")
with open(f"{repo}/inventory/app.py", "a", encoding="utf-8") as stream:
    stream.write('''

LOCK_POLL_SECONDS = 0.01


def _acquire(handle: IO[str], path: Path, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise LockTimeout(path, timeout) from None
            time.sleep(LOCK_POLL_SECONDS)


@contextmanager
def transaction(
    data_file: str | Path | None = None,
    config: Config | None = None,
    clock: Clock = utcnow,
) -> Iterator[App]:
    """Hold the exclusive lock beside the data file, load it fresh, and save only when the block succeeds."""
    config = config or Config.from_env()
    path = Path(data_file if data_file is not None else config.data_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "a+", encoding="utf-8") as handle:
        _acquire(handle, path, config.lock_timeout)
        try:
            app = create_app(path, config, clock)
            yield app
            app.save()
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
''')

replace(repo, "inventory/cli.py", "from .app import App, create_app\n", "from .app import App, create_app, transaction\n")
replace(repo, "inventory/cli.py", "def main(\n", '''WRITE_HANDLERS = frozenset(
    {
        cmd_item_add, cmd_warehouse_add, cmd_stock_receive, cmd_stock_adjust, cmd_order_create, cmd_order_ship,
        cmd_order_cancel, cmd_import_items, cmd_import_stock,
    }
)


def main(
''')
replace(repo, "inventory/cli.py", '''        app = create_app(args.data, Config.from_env(environ))
        args.handler(app, args, out)
''', '''        config = Config.from_env(environ)
        if args.handler in WRITE_HANDLERS:
            with transaction(args.data, config) as app:
                args.handler(app, args, out)
        else:
            args.handler(create_app(args.data, config), args, out)
''')

replace(repo, "README.md", "| `INVENTORY_TAX_RATE` | `0.08` | Tax rate between 0 and 1 added to each order subtotal. |\n",
        "| `INVENTORY_TAX_RATE` | `0.08` | Tax rate between 0 and 1 added to each order subtotal. |\n| `INVENTORY_LOCK_TIMEOUT` | `10` | Seconds a command that changes data waits for the data file lock; 0 fails at once. |\n")
replace(repo, "README.md", "## CSV import\n", '''## Concurrent use

Every command that changes data takes an exclusive lock on `<data file>.lock`, reloads the data file under it, and
saves before releasing it, so several processes can share one data file without overselling stock or losing an update.
A command that cannot get the lock within `INVENTORY_LOCK_TIMEOUT` seconds exits with 2. Read-only commands never wait.

## CSV import
''')
replace(repo, "docs/ko/README.ko.md", "| `INVENTORY_TAX_RATE` | `0.08` | 주문 소계에 더하는 0 이상 1 미만의 세율입니다. |\n",
        "| `INVENTORY_TAX_RATE` | `0.08` | 주문 소계에 더하는 0 이상 1 미만의 세율입니다. |\n| `INVENTORY_LOCK_TIMEOUT` | `10` | 데이터를 바꾸는 명령이 데이터 파일 잠금을 기다리는 시간(초)입니다. 0이면 바로 실패합니다. |\n")
replace(repo, "docs/ko/README.ko.md", "## CSV 가져오기\n", '''## 동시 사용

데이터를 바꾸는 모든 명령은 `<데이터 파일>.lock`에 배타 잠금을 잡고, 잠금 안에서 데이터 파일을 다시 읽은 뒤 저장하고 풀기 때문에
여러 프로세스가 한 데이터 파일을 써도 재고를 초과해 팔거나 갱신이 사라지지 않습니다. `INVENTORY_LOCK_TIMEOUT`초 안에 잠금을 잡지 못한
명령은 종료 코드 2로 끝납니다. 읽기 전용 명령은 기다리지 않습니다.

## CSV 가져오기
''')
