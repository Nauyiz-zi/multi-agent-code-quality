import unittest

from workflow import syntax_check


class TestWorkflow(unittest.TestCase):

    def test_valid_python(self):
        result = syntax_check("x = 1\nprint(x)")
        self.assertTrue(result["passed"])

    def test_invalid_python(self):
        result = syntax_check("def broken(:")
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()