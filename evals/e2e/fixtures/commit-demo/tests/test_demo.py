from src.demo import greet


def test_greet_uses_the_name():
    assert greet("world") == "hello world"
