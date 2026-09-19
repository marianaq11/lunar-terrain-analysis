import unittest
import numpy as np
from analyze import ROOT, read_grid, sample_grid, summarize


class AnalysisTests(unittest.TestCase):
    def test_pixel_centers_and_orientation(self):
        frame = sample_grid(np.array([[10., 20.], [30., 40.]]), 1)
        self.assertEqual(frame.latitude_deg.tolist(), [45, 45, -45, -45])
        self.assertEqual(frame.longitude_deg_east.tolist(), [90, 270, 90, 270])
        self.assertEqual(frame.elevation_m.tolist(), [10, 20, 30, 40])

    def test_weighted_mean_for_constant_surface(self):
        summary = summarize(sample_grid(np.full((8, 16), 50.), 1))
        self.assertAlmostEqual(summary['area_weighted_mean_elevation_m'], 50.)

    def test_real_data_count_and_units(self):
        grid = read_grid(ROOT / 'data')
        self.assertEqual(grid.shape, (720, 1440))
        self.assertEqual(len(sample_grid(grid, 8)), 16200)
        self.assertEqual(grid.min(), -8878.5)
        self.assertEqual(grid.max(), 10504.)

    def test_invalid_step(self):
        with self.assertRaises(ValueError):
            sample_grid(np.zeros((4, 4)), 0)


if __name__ == '__main__':
    unittest.main()
