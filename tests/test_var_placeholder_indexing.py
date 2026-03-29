import unittest

import sympy as sp

from mtex_executor import reemplazar_vars


class VarPlaceholderIndexingTests(unittest.TestCase):
    def test_var_placeholder_supports_one_based_list_indexing(self):
        ctx = {"sol_h": [2, 3]}
        rendered = reemplazar_vars(r"x_1=\var{sol_h[1]}, x_2=\var{sol_h[2]}", ctx)
        self.assertIn("x_1=2", rendered)
        self.assertIn("x_2=3", rendered)

    def test_var_placeholder_supports_two_dimensional_matrix_indexing(self):
        ctx = {"A": sp.Matrix([[1, 2], [3, 4]])}
        rendered = reemplazar_vars(r"\var{A[2,1]}", ctx)
        self.assertEqual("3", rendered)


if __name__ == "__main__":
    unittest.main()
