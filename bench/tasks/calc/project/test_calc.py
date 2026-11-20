import unittest

from calc import evaluate


class EvaluateTest(unittest.TestCase):
    def test_addition(self):
        self.assertEqual(evaluate("1+2"), 3)

    def test_precedence(self):
        self.assertEqual(evaluate("2+3*4"), 14)

    def test_parentheses(self):
        self.assertEqual(evaluate("(2+3)*4"), 20)

    def test_unary_minus(self):
        self.assertEqual(evaluate("-3+5"), 2)

    def test_nested_parentheses(self):
        self.assertEqual(evaluate("2*(3+(4-1))"), 12)

    def test_division_is_integer_floor(self):
        self.assertEqual(evaluate("7/2"), 3)

    def test_rejects_dangling_operator(self):
        with self.assertRaises(ValueError):
            evaluate("1+")

    def test_rejects_unknown_char(self):
        with self.assertRaises(ValueError):
            evaluate("1%2")


if __name__ == "__main__":
    unittest.main()
