#!/usr/bin/env python3

import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

from wyzebridge import mtx_server


class TestKVSMtxOnDemandConfig(unittest.TestCase):
    def test_kvs_paths_force_source_on_demand(self):
        writes = {}

        class FakeMtxInterface:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, exc_type, exc, tb):
                return False

            def set(self_inner, path, value):
                writes[path] = value

            def save_config(self_inner):
                return None

        with patch.object(mtx_server, "MtxInterface", FakeMtxInterface):
            mtx_server.MtxServer().add_path("deck", on_demand=False, is_kvs=True)

        self.assertEqual(
            writes["paths.deck.source"],
            f"whep://127.0.0.1:{mtx_server.WHEP_PROXY_PORT}/whep/deck",
        )
        self.assertTrue(writes["paths.deck.sourceOnDemand"])
        self.assertEqual(writes["paths.deck.sourceOnDemandStartTimeout"], "30s")
        self.assertEqual(writes["paths.deck.sourceOnDemandCloseAfter"], "30s")
        self.assertEqual(writes["paths.deck.whepTrackGatherTimeout"], "8s")


if __name__ == "__main__":
    unittest.main()
