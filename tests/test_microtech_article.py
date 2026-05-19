import os
import unittest

from microtech.services import MicrotechArtikelService, microtech_connection


def _has_env() -> bool:
    return bool(os.getenv("MICROTECH_GRAPHQL_URL"))


class MicrotechArticleReadTest(unittest.TestCase):
    @unittest.skipUnless(_has_env(), "Missing MICROTECH_GRAPHQL_URL environment variable")
    def test_read_article_204113(self):
        with microtech_connection() as erp:
            service = MicrotechArtikelService(erp=erp)

            found = service.find("204113", index_field="ArtNr")
            if not found:
                found = service.find("204113")

            self.assertTrue(found, "Article 204113 not found in Microtech dataset")
            self.assertTrue(service.get_field("ArtNr"), "ArtNr field is empty")


if __name__ == "__main__":
    unittest.main()
