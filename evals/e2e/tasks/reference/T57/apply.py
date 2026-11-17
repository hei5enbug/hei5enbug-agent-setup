import os
import sys

from patch_tools import append, replace

repo = sys.argv[1]
skipped = {name for name in os.environ.get("T57_SKIP_AREAS", "").split(",") if name}


def catalog() -> None:
    replace(repo, "inventory/models.py", "    category: str = \"general\"\n    active: bool = True\n",
            "    category: str = \"general\"\n    active: bool = True\n    tags: list[str] = field(default_factory=list)\n")
    replace(repo, "inventory/validators.py", "MAX_QUANTITY = 1_000_000\n",
            "MAX_QUANTITY = 1_000_000\nTAG_PATTERN = re.compile(r\"^[a-z0-9][a-z0-9-]{0,23}$\")\n")
    append(repo, "inventory/validators.py", '''

def validate_tag(tag: str) -> str:
    cleaned = tag.strip().lower()
    if not TAG_PATTERN.match(cleaned):
        raise ValidationError(f"invalid tag: {tag!r}")
    return cleaned
''')
    replace(repo, "inventory/items.py", "from .validators import validate_name, validate_sku\n",
            "from .validators import validate_name, validate_sku, validate_tag\n\nMAX_TAGS = 5\n")
    replace(repo, "inventory/items.py", "    def deactivate(self, sku: str) -> Item:",
            '''    def add_tag(self, sku: str, tag: str) -> Item:
        item = self.get_item(sku)
        cleaned = validate_tag(tag)
        if cleaned not in item.tags:
            if len(item.tags) >= MAX_TAGS:
                raise ValidationError(f"item {item.sku} can have at most {MAX_TAGS} tags")
            item.tags = sorted([*item.tags, cleaned])
        return item

    def remove_tag(self, sku: str, tag: str) -> Item:
        item = self.get_item(sku)
        cleaned = validate_tag(tag)
        if cleaned not in item.tags:
            raise ValidationError(f"item {item.sku} has no tag {cleaned}")
        item.tags = [existing for existing in item.tags if existing != cleaned]
        return item

    def deactivate(self, sku: str) -> Item:''')
    replace(repo, "inventory/items.py", "    def list_items(self, *, category: str | None = None, include_inactive: bool = False) -> list[Item]:\n        wanted = category.strip().lower() if category else None\n",
            "    def list_items(\n        self, *, category: str | None = None, include_inactive: bool = False, tag: str | None = None\n    ) -> list[Item]:\n        wanted = category.strip().lower() if category else None\n        wanted_tag = validate_tag(tag) if tag else None\n")
    replace(repo, "inventory/items.py", "            if (include_inactive or item.active) and (wanted is None or item.category == wanted)\n",
            "            if (include_inactive or item.active)\n            and (wanted is None or item.category == wanted)\n            and (wanted_tag is None or wanted_tag in item.tags)\n")
    append(repo, "inventory/items.py", '''
    def tag_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.db.items.values():
            if item.active:
                for tag in item.tags:
                    counts[tag] = counts.get(tag, 0) + 1
        return dict(sorted(counts.items()))
''')


def storage() -> None:
    replace(repo, "inventory/serialization.py", "SCHEMA_VERSION = 1\n", "SCHEMA_VERSION = 2\n")
    replace(repo, "inventory/serialization.py", '        "active": item.active,\n    }',
            '        "active": item.active,\n        "tags": list(item.tags),\n    }')
    replace(repo, "inventory/serialization.py", "def item_from_dict(data: dict[str, Any]) -> Item:\n    return Item(",
            '''def _tags(raw: Any) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(tag, str) for tag in raw):
        raise ValueError(f"tags must be a list of strings: {raw!r}")
    return sorted({tag.strip().lower() for tag in raw})


def item_from_dict(data: dict[str, Any]) -> Item:
    return Item(''')
    replace(repo, "inventory/serialization.py", '        active=data.get("active", True),\n    )',
            '        active=data.get("active", True),\n        tags=_tags(data.get("tags", [])),\n    )')


def cli() -> None:
    replace(repo, "inventory/formatting.py",
            '    rows = [[item.sku, item.name, item.category, format_money(item.unit_price)] for item in items]\n    return render_table(["SKU", "NAME", "CATEGORY", "PRICE"], rows)',
            '    rows = [\n        [item.sku, item.name, item.category, format_money(item.unit_price), ",".join(item.tags) or "-"]\n        for item in items\n    ]\n    return render_table(["SKU", "NAME", "CATEGORY", "PRICE", "TAGS"], rows)')
    replace(repo, "inventory/cli.py", "    listing.add_argument(\"--category\")\n    listing.set_defaults(handler=cmd_item_list)\n",
            '''    listing.add_argument("--category")
    listing.add_argument("--tag")
    listing.set_defaults(handler=cmd_item_list)
    for name, handler in (("tag", cmd_item_tag), ("untag", cmd_item_untag)):
        change = item.add_parser(name, help=f"{name} an item")
        change.add_argument("sku")
        change.add_argument("tag")
        change.set_defaults(handler=handler)
    item.add_parser("tags", help="count items per tag").set_defaults(handler=cmd_item_tags)
''')
    replace(repo, "inventory/cli.py", "    print(formatting.render_items(app.catalog.list_items(category=args.category)), file=out)\n",
            '''    print(formatting.render_items(app.catalog.list_items(category=args.category, tag=args.tag)), file=out)


def cmd_item_tag(app: App, args: argparse.Namespace, out: TextIO) -> None:
    item = app.catalog.add_tag(args.sku, args.tag)
    app.save()
    print(f"Tagged {item.sku} with {args.tag.strip().lower()}", file=out)


def cmd_item_untag(app: App, args: argparse.Namespace, out: TextIO) -> None:
    item = app.catalog.remove_tag(args.sku, args.tag)
    app.save()
    print(f"Removed tag {args.tag.strip().lower()} from {item.sku}", file=out)


def cmd_item_tags(app: App, args: argparse.Namespace, out: TextIO) -> None:
    rows = [[tag, str(count)] for tag, count in app.catalog.tag_counts().items()]
    print(formatting.render_table(["TAG", "ITEMS"], rows), file=out)
''')


def docs() -> None:
    replace(repo, "README.md", "## Configuration\n",
            "## Item tags\n\n`item tag SKU TAG` and `item untag SKU TAG` change an item's tags (at most 5 per item). `item list --tag TAG`\nlists the items with a tag, and `item tags` prints the number of active items per tag.\n\n## Configuration\n")
    replace(repo, "docs/ko/README.ko.md", "## 설정\n",
            "## 품목 태그\n\n`item tag SKU TAG`와 `item untag SKU TAG`는 품목의 태그를 바꿉니다(품목당 최대 5개). `item list --tag TAG`는 그 태그를 가진\n품목을 보여 주고, `item tags`는 활성 품목의 태그별 개수를 출력합니다.\n\n## 설정\n")


for name, apply in (("catalog", catalog), ("storage", storage), ("cli", cli)):
    if name not in skipped:
        apply()
docs()
