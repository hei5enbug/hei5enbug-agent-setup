import unittest
from pathlib import Path


class SubTestParameterGuardTest(unittest.TestCase):
    def test_Path_하위_테스트_매개변수는_매개변수_이름과_형식을_밝히며_실패한다(self):
        """xdist가 직렬화하지 못하는 Path 값을 subTest에 넘기면 매개변수 이름과 형식을 밝히며 실패한다."""
        # Given
        parameter = Path("docs") / "demo.md"

        # When
        with self.assertRaises(AssertionError) as raised:
            with self.subTest(path=parameter):
                pass

        # Then
        message = str(raised.exception)
        self.assertIn("path", message)
        self.assertIn(type(parameter).__name__, message)

    def test_str_하위_테스트_매개변수는_그대로_통과한다(self):
        """str과 숫자와 이들로만 이루어진 튜플과 목록은 subTest에서 그대로 통과한다."""
        # Given
        parameters = {"path": "docs/demo.md", "count": 2, "ratio": 0.5, "flag": True, "none": None, "pair": ("a", 1)}
        executed = []

        # When
        with self.subTest(**parameters):
            executed.append(True)

        # Then
        self.assertEqual(executed, [True])

    def test_Path가_든_목록_매개변수도_실패한다(self):
        """직렬화할 수 없는 값이 든 목록도 subTest에서 실패한다."""
        # Given
        parameter = [Path("docs")]

        # When
        with self.assertRaises(AssertionError) as raised:
            with self.subTest(paths=parameter):
                pass

        # Then
        self.assertIn("paths", str(raised.exception))
