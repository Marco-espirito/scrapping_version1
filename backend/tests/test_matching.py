import unittest

from matching import _count_hits, _extract_salary, _normalize


class MatchingTests(unittest.TestCase):
    def test_term_does_not_match_inside_another_word(self):
        haystack = _normalize("Un poste de développeur avec des avantages")
        self.assertEqual(_count_hits(["stage"], haystack), (0, []))

    def test_punctuated_skill_matches(self):
        haystack = _normalize("Développement en C++ et .NET")
        self.assertEqual(_count_hits(["C++", ".NET"], haystack)[0], 2)

    def test_salary_formats_are_annualized(self):
        self.assertEqual(_extract_salary("45k € par an"), 45000)
        self.assertEqual(_extract_salary("2 500 € / mois"), 30000)
        self.assertEqual(_extract_salary("20 € / h"), 36400)


if __name__ == "__main__":
    unittest.main()
