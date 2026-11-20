import unittest

from csvkit import parse_line, parse_rows, serialize_row


class ParseTest(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(parse_line("a,b,c"), ["a", "b", "c"])

    def test_quoted_comma(self):
        self.assertEqual(parse_line('a,"b,c",d'), ["a", "b,c", "d"])

    def test_doubled_quote_is_one_quote(self):
        self.assertEqual(parse_line('"he said ""hi"""'), ['he said "hi"'])

    def test_empty_fields(self):
        self.assertEqual(parse_line("a,,c"), ["a", "", "c"])


class SerializeTest(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(serialize_row(["a", "b"]), "a,b")

    def test_quote_inside_field_is_escaped(self):
        self.assertEqual(serialize_row(['he said "hi"']), '"he said ""hi"""')

    def test_roundtrip(self):
        original = ["a", "b,c", 'd"e']
        self.assertEqual(parse_line(serialize_row(original)), original)


class RowsTest(unittest.TestCase):
    def test_skips_blank_lines(self):
        self.assertEqual(parse_rows("a,b\n\nc,d\n"), [["a", "b"], ["c", "d"]])


if __name__ == "__main__":
    unittest.main()
