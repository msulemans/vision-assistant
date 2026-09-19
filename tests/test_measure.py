from __future__ import annotations

import unittest

from vision_assistant.measure import (
    PeakSampler,
    ProcessTreeSampler,
    parse_ps_rss_mib,
    parse_swap_used_mib,
)


class _Result:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


class MeasureParseTest(unittest.TestCase):
    def test_parse_ps_rss_sums_kib_rows(self) -> None:
        self.assertEqual(parse_ps_rss_mib("2048\n1024\n"), 3.0)
        self.assertEqual(parse_ps_rss_mib("  4096  \n\n"), 4.0)
        self.assertEqual(parse_ps_rss_mib(""), 0.0)

    def test_parse_swap_used(self) -> None:
        text = "total = 2048.00M  used = 512.25M  free = 1535.75M  (encrypted)"
        self.assertEqual(parse_swap_used_mib(text), 512.25)
        self.assertEqual(parse_swap_used_mib("unexpected"), 0.0)


class MeasureSamplerTest(unittest.TestCase):
    def test_process_tree_sampler_sums_parent_and_children(self) -> None:
        def runner(args, **kwargs):
            if "--ppid" in args:
                return _Result("  123\n  456\n")
            pid = args[-1]
            return _Result({"111": "2048\n", "123": "1024\n", "456": "3072\n"}.get(pid, "0\n"))

        sampler = ProcessTreeSampler(111, runner=runner)
        self.assertEqual(sampler.pids(), [111, 123, 456])
        self.assertEqual(sampler.sample_mib(), 6.0)

    def test_peak_sampler_records_swap_growth(self) -> None:
        class Tree:
            def sample_mib(self) -> float:
                return 6.0

        swaps = iter([10.0, 150.0])
        sampler = PeakSampler(1, interval_s=0.01, tree=Tree(), swap_reader=lambda: next(swaps))
        sampler.start()
        sampler.stop()
        self.assertGreaterEqual(sampler.peak_mib, 0.0)
        self.assertEqual(sampler.swap_end_mib - sampler.swap_start_mib, 140.0)


if __name__ == "__main__":
    unittest.main()
