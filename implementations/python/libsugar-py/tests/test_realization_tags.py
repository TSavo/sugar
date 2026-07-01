import unittest

from libsugar_py.realization_tags import (
    BoundaryRealization,
    CompositionRealization,
    FirstClassRealization,
    SugarCarrierRealization,
    tag_boundary,
    tag_composition,
    tag_first_class,
    tag_sugar_carrier,
)

COMPOSITION_TREE_CID = "blake3-512:" + "1" * 128
BOUNDARY_CONTRACT_CID = "blake3-512:" + "2" * 128


class RealizationTagsTest(unittest.TestCase):
    def test_tag_first_class_builds_first_class_realization(self) -> None:
        realization = tag_first_class("concept:add", "${x} + ${y}", "binary-operator")

        self.assertEqual(
            realization,
            FirstClassRealization(
                syntactic_pattern="${x} + ${y}",
                surface_locator="binary-operator",
            ),
        )

    def test_tag_composition_builds_composition_realization(self) -> None:
        realization = tag_composition("concept:list", COMPOSITION_TREE_CID)

        self.assertEqual(
            realization,
            CompositionRealization(
                composition_tree_cid=COMPOSITION_TREE_CID,
            ),
        )

    def test_tag_boundary_builds_boundary_realization(self) -> None:
        realization = tag_boundary(
            "concept:http-request",
            "python-requests",
            "requests.get",
            BOUNDARY_CONTRACT_CID,
        )

        self.assertEqual(
            realization,
            BoundaryRealization(
                library="python-requests",
                api="requests.get",
                boundary_contract_cid=BOUNDARY_CONTRACT_CID,
            ),
        )

    def test_tag_sugar_carrier_builds_sugar_carrier_realization(self) -> None:
        realization = tag_sugar_carrier("concept:free")

        self.assertEqual(realization, SugarCarrierRealization())

    def test_tagging_primitives_have_distinct_cids(self) -> None:
        cids = {
            tag_first_class(
                "concept:add", "${x} + ${y}", "binary-operator"
            ).recompute_cid(),
            tag_composition("concept:add", COMPOSITION_TREE_CID).recompute_cid(),
            tag_boundary(
                "concept:add",
                "python-requests",
                "requests.get",
                BOUNDARY_CONTRACT_CID,
            ).recompute_cid(),
            tag_sugar_carrier("concept:add").recompute_cid(),
        }

        self.assertEqual(len(cids), 4)


if __name__ == "__main__":
    unittest.main()
