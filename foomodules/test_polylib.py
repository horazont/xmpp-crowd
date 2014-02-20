import unittest

from .polylib import IntField, FieldPoly

class TestIntField(unittest.TestCase):
    def test_GF5(self):
        field = IntField(5)
        self.assertEqual(
            1 // field(1),
            field(1))
        self.assertEqual(
            1 // field(2),
            field(3))
        self.assertEqual(
            1 // field(3),
            field(2))
        self.assertEqual(
            1 // field(4),
            field(4))

        self.assertEqual(
            field(2) // field(1),
            2)

        self.assertEqual(
            field(2) + field(3),
            0)

        self.assertEqual(
            field(2) + 3,
            0)

        self.assertEqual(
            field(2)*4,
            3)

class TestFieldPoly(unittest.TestCase):
    def test_compress(self):
        field = IntField(5)
        poly = FieldPoly(field, [0, 1, 1, 0, 0])
        poly._compress()
        self.assertEqual(poly.cs, [0, 1, 1])

    def test_divmod(self):
        field = IntField(5)
        self.assertEqual(
            divmod(FieldPoly(field, [0, 0, 0, 0, 2]),
                   FieldPoly(field, [0, 1, 0, 1])),
            (FieldPoly(field, [0, 2]),
             FieldPoly(field, [0, 0, 3])))

        self.assertEqual(
            divmod(FieldPoly(field, [0, 0, 0, 0, 2]),
                   FieldPoly(field, [0, 1, 0, 3])),
            (FieldPoly(field, [0, 4]),
             FieldPoly(field, [0, 0, 1])))

        self.assertEqual(
            divmod(FieldPoly(field, [0, 0, 1, 2]),
                   FieldPoly(field, [0, 0, 1])),
            (FieldPoly(field, [1, 2]),
             FieldPoly(field, [])))
