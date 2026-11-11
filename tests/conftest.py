import pytest

HEALTHY_MACHINE = "1,8,0.5,0.5"


@pytest.fixture(autouse=True)
def healthy_machine(monkeypatch):
    """한 컴퓨터의 실제 부하와 남은 공간이 프롬프트 맥락 줄을 바꾸지 않도록 모든 시험에서 건강한 값을 주입한다."""
    monkeypatch.setenv("HEI5ENBUG_MACHINE_COUNTERS_FOR_TESTS", HEALTHY_MACHINE)
