from dockit import features


def test_features_are_found_by_module_name_and_their_migrations_are_collected():
    assert "visits" in [module.__name__.rsplit(".", 1)[-1] for module in features.modules()]
    assert "create-visits" in [name for name, _ in features.migrations()]
