import sys

from patch_tools import append, replace

repo = sys.argv[1]

replace(repo, "inventory/models.py", "    cancelled_at: datetime | None = None\n\n\n@dataclass(frozen=True)\nclass AuditEntry",
        '    cancelled_at: datetime | None = None\n    shipping_method: str = "standard"\n    shipping_fee: Decimal = Decimal("0.00")\n\n\n@dataclass(frozen=True)\nclass AuditEntry')
replace(repo, "inventory/serialization.py", '        "cancelled_at": _iso(order.cancelled_at),\n',
        '        "cancelled_at": _iso(order.cancelled_at),\n        "shipping_method": order.shipping_method,\n        "shipping_fee": str(order.shipping_fee),\n')
replace(repo, "inventory/serialization.py", '        cancelled_at=_dt(data.get("cancelled_at")),\n    )',
        '        cancelled_at=_dt(data.get("cancelled_at")),\n        shipping_method=data.get("shipping_method", "standard"),\n        shipping_fee=Decimal(data.get("shipping_fee", "0.00")),\n    )')
replace(repo, "inventory/config.py", "from .errors import ConfigError\n", "from .errors import ConfigError\nfrom .shipping import ShippingPolicy\n")
replace(repo, "inventory/config.py", "    tax_rate: Decimal = DEFAULT_TAX_RATE\n",
        "    tax_rate: Decimal = DEFAULT_TAX_RATE\n    shipping_policy: ShippingPolicy = ShippingPolicy()\n")
replace(repo, "inventory/config.py", '            tax_rate=_read_rate(env.get("INVENTORY_TAX_RATE"), DEFAULT_TAX_RATE),\n',
        '            tax_rate=_read_rate(env.get("INVENTORY_TAX_RATE"), DEFAULT_TAX_RATE),\n            shipping_policy=_read_shipping(env),\n')
append(repo, "inventory/config.py", '''

def _read_amount(env: Mapping[str, str], name: str, default: Decimal) -> Decimal:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = Decimal(raw.strip())
    except InvalidOperation as exc:
        raise ConfigError(f"{name} must be a decimal amount, got {raw!r}") from exc
    if not value.is_finite() or value < 0:
        raise ConfigError(f"{name} must not be negative, got {raw!r}")
    return value


def _read_shipping(env: Mapping[str, str]) -> ShippingPolicy:
    defaults = ShippingPolicy()
    return ShippingPolicy(
        flat_fee=_read_amount(env, "INVENTORY_SHIPPING_FEE", defaults.flat_fee),
        free_threshold=_read_amount(env, "INVENTORY_FREE_SHIPPING_MIN", defaults.free_threshold),
        express_surcharge=_read_amount(env, "INVENTORY_EXPRESS_SURCHARGE", defaults.express_surcharge),
    )
''')
replace(repo, "inventory/orders.py", "from .pricing import PriceCalculator\n", "from .pricing import PriceCalculator\nfrom .shipping import SHIPPING_METHODS, ShippingPolicy\n")
replace(repo, "inventory/orders.py", "        clock: Clock = utcnow,\n    ) -> None:\n        self.db = db",
        "        clock: Clock = utcnow,\n        shipping_policy: ShippingPolicy | None = None,\n    ) -> None:\n        self.shipping_policy = shipping_policy or ShippingPolicy()\n        self.db = db")
replace(repo, "inventory/orders.py", "    def create_order(self, customer: str, requests: Sequence[OrderRequest]) -> Order:",
        '    def create_order(self, customer: str, requests: Sequence[OrderRequest], shipping: str = "standard") -> Order:')
replace(repo, "inventory/orders.py", '            raise ValidationError("customer must not be empty")\n',
        '            raise ValidationError("customer must not be empty")\n        if shipping not in SHIPPING_METHODS:\n            raise ValidationError(f"unknown shipping method: {shipping!r}")\n')
replace(repo, "inventory/orders.py", "        totals = self.calculator.totals([line.line_total for line in lines])\n",
        "        totals = self.calculator.totals([line.line_total for line in lines])\n        fee = self.shipping_policy.quote(totals.subtotal, shipping)\n")
replace(repo, "inventory/orders.py", "            total=totals.total,\n        )",
        "            total=totals.total + fee,\n            shipping_method=shipping,\n            shipping_fee=fee,\n        )")
replace(repo, "inventory/app.py", "PriceCalculator(config.tax_rate), clock)", "PriceCalculator(config.tax_rate), clock, config.shipping_policy)")
replace(repo, "inventory/cli.py", '    create.add_argument("--line", action="append", required=True, metavar="SKU=QTY")\n',
        '    create.add_argument("--line", action="append", required=True, metavar="SKU=QTY")\n    create.add_argument("--shipping", choices=("standard", "express"), default="standard")\n')
replace(repo, "inventory/cli.py", "[parse_line(spec) for spec in args.line])", "[parse_line(spec) for spec in args.line], args.shipping)")
replace(repo, "inventory/formatting.py", '    lines.append(f"Total: {format_money(order.total)}")',
        '    lines.append(f"Shipping: {format_money(order.shipping_fee)} ({order.shipping_method})")\n    lines.append(f"Total: {format_money(order.total)}")')
replace(repo, "README.md", "| `INVENTORY_TAX_RATE` | `0.08` | Tax rate between 0 and 1 added to each order subtotal. |\n",
        "| `INVENTORY_TAX_RATE` | `0.08` | Tax rate between 0 and 1 added to each order subtotal. |\n"
        "| `INVENTORY_SHIPPING_FEE` | `5.00` | Standard shipping fee for orders below the free-shipping minimum. |\n"
        "| `INVENTORY_FREE_SHIPPING_MIN` | `100.00` | Subtotal from which standard shipping is free. |\n"
        "| `INVENTORY_EXPRESS_SURCHARGE` | `12.00` | Added to the shipping fee of every express order. |\n")
replace(repo, "README.md", "- **Pricing**:", "- **Shipping**: `order create --shipping express` adds the express surcharge. The shipping fee is added to the total; tax only applies to the subtotal.\n- **Pricing**:")
replace(repo, "docs/ko/README.ko.md", "| `INVENTORY_TAX_RATE` | `0.08` | 주문 소계에 더하는 0 이상 1 미만의 세율입니다. |\n",
        "| `INVENTORY_TAX_RATE` | `0.08` | 주문 소계에 더하는 0 이상 1 미만의 세율입니다. |\n"
        "| `INVENTORY_SHIPPING_FEE` | `5.00` | 무료배송 최소 금액 미만 주문의 기본 배송비입니다. |\n"
        "| `INVENTORY_FREE_SHIPPING_MIN` | `100.00` | 기본 배송이 무료가 되는 소계입니다. |\n"
        "| `INVENTORY_EXPRESS_SURCHARGE` | `12.00` | express 주문의 배송비에 더하는 추가요금입니다. |\n")
replace(repo, "docs/ko/README.ko.md", "- **가격**:", "- **배송비**: `order create --shipping express`를 쓰면 express 추가요금이 붙습니다. 배송비는 총액에 더하고, 세금은 소계에만 붙습니다.\n- **가격**:")
