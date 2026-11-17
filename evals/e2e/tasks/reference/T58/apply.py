import sys

from patch_tools import replace

repo = sys.argv[1]
replace(repo, "inventory/storage.py", "        self.path = Path(path)\n",
        "        self.path = Path(path)\n        self.recovered_from_backup = False\n")
replace(repo, "inventory/storage.py", "    def load(self) -> Database:\n        \"\"\"Return the stored database, or an empty one when the file does not exist yet.\"\"\"\n        if not self.path.exists():\n            return Database()\n",
        '''    @property
    def backup_path(self) -> Path:
        return self.path.with_name(self.path.name + ".bak")

    def load(self) -> Database:
        """Return the stored database, or an empty one when the file does not exist yet."""
        if not self.path.exists():
            self.recovered_from_backup = False
            return Database()
        try:
            db = self._load_file(self.path)
        except StorageError:
            if not self.backup_path.exists():
                raise
            try:
                db = self._load_file(self.backup_path)
            except StorageError:
                pass
            else:
                self.recovered_from_backup = True
                return db
            raise
        self.recovered_from_backup = False
        return db

    def restore_backup(self) -> Database:
        """Replace the main file with the backup and return the restored database."""
        try:
            db = self._load_file(self.backup_path)
        except StorageError as exc:
            raise StorageError(f"no usable backup for {self.path}: {exc}") from exc
        self._replace(self.backup_path.read_text(encoding="utf-8"))
        self.recovered_from_backup = False
        return db

    def _load_file(self, path: Path) -> Database:
''')
replace(repo, "inventory/storage.py", "        try:\n            data = json.loads(self.path.read_text(encoding=\"utf-8\"))\n        except (OSError, json.JSONDecodeError) as exc:\n            raise StorageError(f\"cannot read {self.path}: {exc}\") from exc\n        if not isinstance(data, dict):\n            raise StorageError(f\"{self.path} does not contain a JSON object\")",
        "        try:\n            data = json.loads(path.read_text(encoding=\"utf-8\"))\n        except (OSError, json.JSONDecodeError) as exc:\n            raise StorageError(f\"cannot read {path}: {exc}\") from exc\n        if not isinstance(data, dict):\n            raise StorageError(f\"{path} does not contain a JSON object\")")
replace(repo, "inventory/storage.py", "            raise StorageError(f\"{self.path} uses schema {schema}, newer than {SCHEMA_VERSION}\")", "            raise StorageError(f\"{path} uses schema {schema}, newer than {SCHEMA_VERSION}\")")
replace(repo, "inventory/storage.py", "            raise StorageError(f\"{self.path} is corrupt: {exc!r}\") from exc", "            raise StorageError(f\"{path} is corrupt: {exc!r}\") from exc")
replace(repo, "inventory/storage.py", '''    def save(self, db: Database) -> None:
        payload = json.dumps(database_to_dict(db), indent=2, sort_keys=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
''', '''    def save(self, db: Database) -> None:
        payload = json.dumps(database_to_dict(db), indent=2, sort_keys=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            shutil.copyfile(self.path, self.backup_path)
        self._replace(payload + "\\n")

    def _replace(self, text: str) -> None:
''')
replace(repo, "inventory/storage.py", "                stream.write(payload)\n                stream.write(\"\\n\")\n", "                stream.write(text)\n")
replace(repo, "inventory/storage.py", "import os\nimport tempfile\n", "import os\nimport shutil\nimport tempfile\n")
replace(repo, "README.md", "## Configuration\n",
        "## Backups\n\nEvery save keeps the previous data file as `<file>.bak`. When the data file cannot be read, loading falls back to the\nbackup, and `JsonStore.restore_backup()` puts the backup back as the data file.\n\n## Configuration\n")
replace(repo, "docs/ko/README.ko.md", "## 설정\n",
        "## 백업\n\n저장할 때마다 이전 데이터 파일을 `<파일>.bak`으로 남깁니다. 데이터 파일을 읽을 수 없으면 백업에서 불러오고,\n`JsonStore.restore_backup()`은 백업을 데이터 파일로 되돌립니다.\n\n## 설정\n")
