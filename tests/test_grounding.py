from __future__ import annotations

import unittest

from vision_assistant.ax_vision import AxElement
from vision_assistant.grounding import (
    TargetSpec,
    capture_consistent,
    element_state,
    ground_target,
    image_region_for_frame,
    normalize,
    region_close,
    resolve_target,
    score_label,
)

WINDOW = (120.0, 80.0, 520.0, 340.0)


def _element(
    path: str = "w0/0",
    *,
    role: str = "AXButton",
    title: str | None = None,
    description: str | None = None,
    value: str | None = None,
    identifier: str | None = None,
    frame: tuple[float, float, float, float] | None = (0.0, 0.0, 10.0, 10.0),
    depth: int = 0,
    secure: bool = False,
    enabled: bool | None = True,
    focused: bool | None = False,
) -> AxElement:
    return AxElement(
        role=role,
        subrole=None,
        title=title,
        description=description,
        value=value,
        identifier=identifier,
        frame=frame,
        enabled=enabled,
        focused=focused,
        secure=secure,
        depth=depth,
        path=path,
    )


class AlignmentTest(unittest.TestCase):
    def test_retina_scale_maps_points_to_pixels(self) -> None:
        frame = (150.0, 100.0, 100.0, 30.0)
        region = image_region_for_frame(frame, WINDOW, (1040, 680))
        self.assertEqual(region, (60, 40, 200, 60))

    def test_1x_keeps_offsets(self) -> None:
        frame = (250.0, 260.0, 116.0, 28.0)
        region = image_region_for_frame(frame, WINDOW, (520, 340))
        self.assertEqual(region, (130, 180, 116, 28))

    def test_element_outside_the_window_is_not_placeable(self) -> None:
        frame = (10.0, 10.0, 40.0, 20.0)  # left/above the window origin
        self.assertIsNone(image_region_for_frame(frame, WINDOW, (520, 340)))

    def test_partial_overlap_is_clipped(self) -> None:
        frame = (100.0, 80.0, 40.0, 20.0)  # starts 20 pt left of the window
        region = image_region_for_frame(frame, WINDOW, (520, 340))
        self.assertEqual(region, (0, 0, 20, 20))

    def test_degenerate_inputs_return_none(self) -> None:
        self.assertIsNone(image_region_for_frame((0.0, 0.0, 0.0, 10.0), WINDOW, (520, 340)))
        self.assertIsNone(image_region_for_frame((0.0, 0.0, 10.0, 10.0), (0.0, 0.0, 0.0, 340.0), (520, 340)))
        self.assertIsNone(image_region_for_frame((0.0, 0.0, 10.0, 10.0), WINDOW, (0, 0)))

    def test_capture_consistency_accepts_retina_and_rejects_mismatch(self) -> None:
        self.assertTrue(capture_consistent(WINDOW, (520, 340)))
        self.assertTrue(capture_consistent(WINDOW, (1040, 680)))
        self.assertFalse(capture_consistent(WINDOW, (1040, 300)))

    def test_region_close_uses_tolerance(self) -> None:
        self.assertTrue(region_close((10, 10, 50, 20), (12, 8, 50, 22), tolerance=2))
        self.assertFalse(region_close((10, 10, 50, 20), (13, 10, 50, 20), tolerance=2))


class ScoreLabelTest(unittest.TestCase):
    def test_normalize_collapses_punctuation_and_case(self) -> None:
        self.assertEqual(normalize("  Save & Close!  "), "save close")

    def test_exact_and_subset_and_core_scores(self) -> None:
        self.assertEqual(score_label("SYNC", "SYNC"), 1.0)
        self.assertEqual(score_label("sync", "Sync Backup"), 0.9)
        self.assertEqual(score_label("cancel", "Cancel Changes"), 0.9)
        self.assertEqual(score_label("search field", "SEARCH"), 0.75)
        self.assertEqual(score_label("the save button", "SAVE"), 0.75)

    def test_unexplained_query_words_do_not_match(self) -> None:
        self.assertEqual(score_label("SAVE ALL", "SAVE"), 0.0)
        self.assertEqual(score_label("DELETE", "DISCARD"), 0.0)


class ResolveTargetTest(unittest.TestCase):
    def _elements(self) -> tuple[AxElement, ...]:
        return (
            _element("w0/0", role="AXCheckBox", title="SYNC", identifier="prefs.sync.primary", value="0"),
            _element("w0/1", role="AXCheckBox", title="SYNC", identifier="prefs.sync.backup", value="0", depth=0),
            _element("w0/2", role="AXStaticText", title="PREFERENCES"),
            _element("w0/3", role="AXTextField", title="SEARCH", identifier="prefs.search", value=""),
            _element("w0/4", role="AXButton", title="SAVE", identifier="prefs.save"),
        )

    def test_role_filter_selects_the_right_kind(self) -> None:
        elements = self._elements()
        result = resolve_target(elements, TargetSpec("search field", role="textfield"))
        self.assertEqual(result.status, "found")
        self.assertEqual(result.chosen.element.path, "w0/3")

    def test_stable_identifier_beats_duplicate_labels(self) -> None:
        elements = self._elements()
        result = resolve_target(elements, TargetSpec("sync", element_id="prefs.sync.backup"))
        self.assertEqual(result.status, "found")
        self.assertEqual(result.chosen.element.path, "w0/1")
        self.assertIn("identifier", result.chosen.reasons)

    def test_unknown_identifier_fails_closed(self) -> None:
        result = resolve_target(self._elements(), TargetSpec("sync", element_id="prefs.missing"))
        self.assertEqual(result.status, "not_found")
        self.assertIsNone(result.chosen)

    def test_duplicate_labels_without_identifier_are_ambiguous(self) -> None:
        result = resolve_target(self._elements(), TargetSpec("SYNC", role="checkbox"))
        self.assertEqual(result.status, "ambiguous")
        self.assertIsNone(result.chosen)
        self.assertGreaterEqual(len(result.alternatives), 2)

    def test_absent_target_is_not_found(self) -> None:
        result = resolve_target(self._elements(), TargetSpec("DELETE"))
        self.assertEqual(result.status, "not_found")

    def test_clear_winner_is_not_flagged_ambiguous(self) -> None:
        elements = (
            _element("w0/0", title="SYNC", role="AXCheckBox"),
            _element("w0/1", title="SYNC BACKUP", role="AXCheckBox"),
        )
        result = resolve_target(elements, TargetSpec("sync", role="checkbox"))
        self.assertEqual(result.status, "found")
        self.assertEqual(result.chosen.element.path, "w0/0")

    def test_ground_attaches_region_and_state(self) -> None:
        elements = self._elements()
        frame = (150.0, 168.0, 300.0, 26.0)
        element = _element("w0/9", role="AXTextField", title="SEARCH", frame=frame, value="")
        result = ground_target((element,), WINDOW, (520, 340), TargetSpec("search field"))
        self.assertEqual(result.status, "found")
        self.assertEqual(result.chosen.region, (30, 88, 300, 26))
        self.assertEqual(result.chosen.state["value"], "")

    def test_secure_values_never_surface_in_state(self) -> None:
        element = _element("w0/0", role="AXTextField", title="PASSWORD", secure=True, value="hunter2")
        state = element_state(element)
        self.assertIsNone(state["value"])
        self.assertNotIn("hunter2", str(state))

    def test_element_without_frame_is_found_but_unplaced(self) -> None:
        element = _element("w0/0", title="FLOATING", frame=None)
        result = ground_target((element,), WINDOW, (520, 340), TargetSpec("floating"))
        self.assertEqual(result.status, "found")
        self.assertIsNone(result.chosen.region)


if __name__ == "__main__":
    unittest.main()
