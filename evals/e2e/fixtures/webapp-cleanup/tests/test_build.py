import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_build_module():
    spec = importlib.util.spec_from_file_location("build_assets", ROOT / "scripts" / "build_assets.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_covers_every_static_file(tmp_path, monkeypatch):
    module = load_build_module()
    monkeypatch.setattr(module, "BUILD", tmp_path / "out")
    manifest = module.build()
    assert sorted(manifest) == sorted(path.name for path in (ROOT / "static").iterdir())
    assert (tmp_path / "out" / "manifest.json").is_file()
