from test_server import Response

from grab import request
from grab.document import normalize_pairs
from tests.util import BaseGrabTestCase


class GrabDocumentTestCase(BaseGrabTestCase):
    def setUp(self):
        self.server.reset()

    def test_document_copy_works(self):
        self.server.add_response(Response(data=b"<h1>test</h1>"))
        res1 = request(self.server.get_url())
        self.assertEqual("test", res1.select("//h1").text())

        res2 = res1.copy()
        self.assertEqual("test", res2.select("//h1").text())

    def test_normalize_pairs_dict(self):
        self.assertEqual(
            normalize_pairs({"foo": "bar"}),
            [("foo", "bar")],
        )

    def test_normalize_pairs_list(self):
        self.assertEqual(
            normalize_pairs([("foo", "bar"), ("1", "2")]),
            [("foo", "bar"), ("1", "2")],
        )
