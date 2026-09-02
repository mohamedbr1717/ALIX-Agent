import unittest
import test_sample
from test_sample import SafeEvalError

class TestTest_Sample(unittest.TestCase):
    def test_basic_arithmetic(self):
        self.assertEqual(test_sample.safe_eval("1+2*3"), 7)

    def test_unary_operations(self):
        self.assertEqual(test_sample.safe_eval("-5"), -5)
        self.assertEqual(test_sample.safe_eval("+5"), 5)
        self.assertTrue(test_sample.safe_eval("not 0"))

    def test_division_by_zero(self):
        with self.assertRaises(SafeEvalError):
            test_sample.safe_eval("1/0")
        with self.assertRaises(SafeEvalError):
            test_sample.safe_eval("1//0")
        with self.assertRaises(SafeEvalError):
            test_sample.safe_eval("5%0")

    def test_power_int_bit_limit(self):
        # 2**2000 has >1024 bits, should be rejected
        with self.assertRaises(SafeEvalError):
            test_sample.safe_eval("2**2000")

    def test_ast_depth_limit(self):
        # 31 nested unary plus operators exceed depth limit of 30
        expr = "+" * 31 + "1"
        with self.assertRaises(SafeEvalError):
            test_sample.safe_eval(expr)

    def test_ast_node_count_limit(self):
        # 501 numbers combined with '+' produce >500 nodes
        expr = "+".join(["1"] * 501)
        with self.assertRaises(SafeEvalError):
            test_sample.safe_eval(expr)

    def test_invalid_syntax(self):
        with self.assertRaises(SafeEvalError):
            test_sample.safe_eval("1++")

    def test_non_string_input(self):
        with self.assertRaises(SafeEvalError):
            test_sample.safe_eval(123)

    def test_boolean_logic(self):
        self.assertFalse(test_sample.safe_eval("True and False"))
        self.assertTrue(test_sample.safe_eval("True or False"))

    def test_comparisons(self):
        self.assertTrue(test_sample.safe_eval("1 < 2 == 2"))
        self.assertFalse(test_sample.safe_eval("3 > 5"))

if __name__ == '__main__':
    unittest.main()