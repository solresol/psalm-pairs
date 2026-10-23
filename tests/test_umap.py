import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
import warnings

try:
    import numpy as np
    import umap
except ImportError:
    np = umap = None


@unittest.skipIf(umap is None, "requires the existing project dependencies")
class UmapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "psalm_pairs/website.py"
        tree = ast.parse(path.read_text())
        names = {"compute_umap_embeddings", "_distance_matrix_from_scores"}
        selected = ast.Module(
            body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names],
            type_ignores=[],
        )
        cls.scope = {"np": np, "umap": umap, "warnings": warnings}
        exec(compile(selected, str(path), "exec"), cls.scope)

    def test_all_three_deterministic_embeddings_are_unchanged(self):
        scores = np.random.RandomState(42).uniform(0, 10, (150, 150))
        for mode in ("minimum", "average", "maximum"):
            with self.subTest(mode=mode):
                distances = self.scope["_distance_matrix_from_scores"](scores, mode)
                with warnings.catch_warnings(record=True):
                    warnings.simplefilter("always")
                    before = umap.UMAP(metric="precomputed", random_state=42).fit_transform(distances)
                with warnings.catch_warnings(record=True) as emitted:
                    warnings.simplefilter("always")
                    after = self.scope["compute_umap_embeddings"](distances)
                self.assertEqual(after.shape, (150, 2))
                self.assertTrue(np.isfinite(after).all())
                self.assertTrue(np.array_equal(before, after))
                self.assertEqual(emitted, [])

    def test_filter_leaves_unexpected_warnings_visible_and_restores_state(self):
        known = "using precomputed metric; inverse_transform will be unavailable"

        class Reducer:
            def fit_transform(self, distance):
                warnings.warn_explicit(known, UserWarning, "umap_.py", 1, module="umap.umap_")
                warnings.warn_explicit("unexpected UMAP warning", UserWarning, "umap_.py", 2, module="umap.umap_")
                warnings.warn_explicit(known, UserWarning, "other.py", 3, module="other")
                warnings.warn_explicit(known, RuntimeWarning, "umap_.py", 4, module="umap.umap_")
                return distance

        old_filters = list(warnings.filters)
        self.scope["umap"] = SimpleNamespace(UMAP=lambda **kwargs: Reducer())
        try:
            with warnings.catch_warnings(record=True) as emitted:
                warnings.simplefilter("always")
                self.scope["compute_umap_embeddings"](np.zeros((20, 20)))
            self.assertEqual([str(w.message) for w in emitted], ["unexpected UMAP warning", known, known])
            self.assertEqual(warnings.filters, old_filters)
        finally:
            self.scope["umap"] = umap

    def test_invalid_input_error_is_not_suppressed(self):
        with self.assertRaises(ValueError):
            self.scope["compute_umap_embeddings"](np.full((20, 20), np.nan))


if __name__ == "__main__":
    unittest.main()
