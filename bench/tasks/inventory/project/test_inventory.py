import unittest

from inventory import add_item, low_stock, merge, total


class MergeTest(unittest.TestCase):
    def test_numbers_add(self):
        self.assertEqual(merge({"a": 1}, {"a": 2}), {"a": 3})

    def test_deep_merge(self):
        base = {"fruit": {"apple": 3}}
        extra = {"fruit": {"pear": 2}}
        self.assertEqual(merge(base, extra), {"fruit": {"apple": 3, "pear": 2}})

    def test_does_not_mutate_inputs(self):
        base = {"fruit": {"apple": 3}}
        merge(base, {"fruit": {"pear": 2}})
        self.assertEqual(base, {"fruit": {"apple": 3}})


class AddItemTest(unittest.TestCase):
    def test_adds_and_accumulates(self):
        stock: dict = {}
        add_item(stock, "fruit", "apple", 2)
        add_item(stock, "fruit", "apple", 1)
        self.assertEqual(stock, {"fruit": {"apple": 3}})

    def test_zero_is_allowed(self):
        stock: dict = {}
        add_item(stock, "fruit", "apple", 0)
        self.assertEqual(stock["fruit"]["apple"], 0)

    def test_negative_rejected(self):
        with self.assertRaises(ValueError):
            add_item({}, "fruit", "apple", -1)


class TotalTest(unittest.TestCase):
    def test_sums_everything(self):
        stock = {"fruit": {"apple": 3, "pear": 2}, "veg": {"kale": 1}}
        self.assertEqual(total(stock), 6)


class LowStockTest(unittest.TestCase):
    def test_threshold_is_inclusive(self):
        stock = {"fruit": {"apple": 2, "pear": 5}}
        self.assertEqual(low_stock(stock, threshold=2), ["fruit/apple"])


if __name__ == "__main__":
    unittest.main()
