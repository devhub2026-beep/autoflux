import unittest

from txtlib import count_words, slugify, title_case, truncate, wrap


class SlugifyTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_punctuation_and_spaces(self):
        self.assertEqual(slugify("  Hello,   World!  "), "hello-world")

    def test_no_leading_trailing_dash(self):
        self.assertEqual(slugify("---Hi there---"), "hi-there")


class TruncateTest(unittest.TestCase):
    def test_short_text_untouched(self):
        self.assertEqual(truncate("abc", 10), "abc")

    def test_result_never_exceeds_limit(self):
        out = truncate("abcdefghij", 5)
        self.assertLessEqual(len(out), 5)


class WrapTest(unittest.TestCase):
    def test_wraps_on_words(self):
        self.assertEqual(wrap("the quick brown fox", 10), ["the quick", "brown fox"])

    def test_long_word_is_hard_cut(self):
        out = wrap("supercalifragilistic", 5)
        self.assertTrue(all(len(line) <= 5 for line in out))


class TitleCaseTest(unittest.TestCase):
    def test_apostrophe_stays_lower(self):
        self.assertEqual(title_case("don't stop"), "Don't Stop")


class CountWordsTest(unittest.TestCase):
    def test_punctuation_only_is_not_a_word(self):
        self.assertEqual(count_words("hello -- world"), 2)


if __name__ == "__main__":
    unittest.main()
