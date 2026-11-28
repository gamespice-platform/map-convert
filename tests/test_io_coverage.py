"""tools/io_coverage.py: gap keys and player chains. Run: python3 -P tests/test_io_coverage.py"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, ".."), os.path.join(HERE, "..", "tools")]
import io_coverage  # noqa: E402
from gsbsp import fidelity, inputs  # noqa: E402


class Bsp:
    def __init__(self, entities):
        self.entities = entities


class IoCoverageTests(unittest.TestCase):
    def test_gap_keys_drop_instances_and_counts(self):
        self.assertEqual(io_coverage.gap_key("volume_parented:trigger_hurt#1674 -> balling_1"), "volume_parented:trigger_hurt")
        self.assertEqual(io_coverage.gap_key("class_unsupported:path_track (approximated)"), "class_unsupported:path_track")
        self.assertEqual(io_coverage.gap_key("player_input:addoutput targetname x5"), "player_input:addoutput targetname")

    def test_a_chain_breaks_at_an_input_the_runtime_does_not_answer(self):
        bsp = Bsp([{"classname": "func_button", "targetname": "b"}, {"classname": "logic_relay", "targetname": "r"},
                   {"classname": "phys_thruster", "targetname": "t"}])
        links = [{"from": 0, "to": [1], "input": "Trigger"}, {"from": 1, "to": [2], "input": "ZzNoSuchInput"}]
        (c,) = io_coverage.chains(bsp, links, {})
        self.assertEqual(c["start"], "func_button b")
        self.assertEqual(c["hops"], ["logic_relay.Trigger", "phys_thruster.ZzNoSuchInput"])
        self.assertEqual(c["broken"], ["input_unimplemented:phys_thruster.ZzNoSuchInput"])

    def test_inputs_tested_outside_a_match_count(self):
        self.assertIn("press", inputs.implemented("func_button"))                  # `if name == "press":`
        self.assertIn("command", inputs.implemented("point_servercommand"))        # `if name != "command": return false`

    def test_class_status_follows_the_runtime_registration(self):
        self.assertEqual(fidelity.runtime_component("trigger_teleport"), "GSMapTeleport")
        self.assertEqual(fidelity.class_status("trigger_teleport", wired=True), "implemented")


if __name__ == "__main__":
    unittest.main()
