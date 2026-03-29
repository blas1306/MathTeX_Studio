import tempfile
import unittest
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from plot_backend import PlotBackend


class PlotBackendDocumentModeTests(unittest.TestCase):
    def test_updates_after_plot_rewrite_same_png(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = PlotBackend(plot_mode="document", output_dir=tmpdir)
            output = backend.plot([0, 1, 2], [0, 1, 4], output_name="demo.png")
            self.assertIsInstance(output, str)

            target = Path(output)  # type: ignore[arg-type]
            self.assertTrue(target.exists())
            before = target.read_bytes()

            backend.title("Parabola")
            backend.xlabel("x")
            backend.ylabel("y")
            backend.set_grid("on")
            backend.legend("serie")

            self.assertEqual(backend._last_document_target, target)
            after = target.read_bytes()
            self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
