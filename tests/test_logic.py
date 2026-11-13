import unittest

from app.services import checks, matcher

CUSTOMERS = [
    {"code": "TAM001", "name": "TEXAS A&M AGRILIFE RESEARCH - PLAINVIEW"},
    {"code": "TAM002", "name": "TEXAS A&M AGRILIFE RESEARCH - MCGREGOR"},
    {"code": "SDG001", "name": "CITY OF SAN DIEGO - ENVIRONMENTAL SERVICES"},
    {"code": "GAR001", "name": "GARLAND INDEPENDENT SCHOOL DISTRICT"},
    {"code": "MBY001", "name": "MBEYA ZONAL REFERRAL HOSPITAL"},
]
PRODUCTS = [
    {"code": "ULG", "description": "Unleaded gasoline", "unit": "gallon"},
    {"code": "DSL",
        "description": "Diesel (clear / highway)", "unit": "gallon"},
    {"code": "DSL-D",
        "description": "Diesel (dyed / off-road)", "unit": "gallon"},
]


class MatcherTests(unittest.TestCase):
    def test_abbreviation_isd(self):
        top = matcher.match_customer("Garland ISD", "", CUSTOMERS)[0]
        self.assertEqual(top["code"], "GAR001")
        self.assertGreaterEqual(top["score"], matcher.AUTO_ACCEPT)

    def test_site_picked_from_address(self):
        top = matcher.match_customer(
            "Texas A&M AgriLife Research", "Plainview, TX", CUSTOMERS)[0]
        self.assertEqual(top["code"], "TAM001")

    def test_unknown_customer_scores_low(self):
        top = matcher.match_customer(
            "Kenya Pipeline Company", "", CUSTOMERS)[0]
        self.assertLess(top["score"], matcher.MIN_ACCEPT)

    def test_products(self):
        self.assertEqual(matcher.match_product(
            "Unleaded Regular Gasoline", PRODUCTS)[0]["code"], "ULG")
        self.assertEqual(matcher.match_product(
            "Dyed diesel #2 off-road", PRODUCTS)[0]["code"], "DSL-D")
        self.assertEqual(matcher.match_product(
            "Clear diesel ULSD", PRODUCTS)[0]["code"], "DSL")

    def test_plain_diesel_is_low_confidence(self):
        self.assertLess(matcher.match_product("Diesel", PRODUCTS)[
                        0]["score"], matcher.AUTO_ACCEPT)

    def test_non_fuel_is_unknown(self):
        self.assertLess(matcher.match_product(
            "Engine lubricant 20W-50", PRODUCTS)[0]["score"], matcher.MIN_ACCEPT)


class ChecksTests(unittest.TestCase):
    def test_line_mismatch_and_doc_total(self):
        data = {
            "is_purchase_order": True,
            "lines": [
                {"quantity": 100, "unit_price": 3, "line_total": 350},
                {"quantity": 10, "unit_price": 2, "line_total": 20},
            ],
            "document_total": 400,
        }
        codes = [f["code"] for f in checks.check_math(data)]
        self.assertIn("LINE_TOTAL_MISMATCH", codes)
        self.assertIn("DOC_TOTAL_MISMATCH", codes)

    def test_clean_document_has_no_math_flags(self):
        data = {"lines": [{"quantity": 100, "unit_price": 3,
                           "line_total": 300}], "document_total": 300}
        self.assertEqual(checks.check_math(data), [])

    def test_not_a_po(self):
        flags = checks.build_flags(
            {"is_purchase_order": False, "document_type": "tender"}, {})
        self.assertEqual(flags[0]["code"], "NOT_A_PO")

    def test_missing_price_is_blocking(self):
        data = {"is_purchase_order": True, "po_number": "1", "lines": [
            {"description": "Diesel", "quantity": 5, "unit_price": None}]}
        match = {
            "customer": {"selected": {"name": "X", "score": 0.95}, "candidates": []},
            "lines": [{"selected": {"code": "DSL", "score": 0.95, "unit": None}}],
        }
        flags = checks.build_flags(data, match)
        self.assertIn("MISSING_PRICE", [f["code"]
                      for f in checks.blocking(flags)])


if __name__ == "__main__":
    unittest.main()
