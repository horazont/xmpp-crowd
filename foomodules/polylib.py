#!/usr/bin/python3

def listsub(a, b):
    if len(a) != len(b):
        raise ValueError("lists must be same length")
    return list(a-b for a, b in zip(a, b))

def listshift(l, shift_by, pad_with=0):
    if shift_by == 0:
        return list(l)
    return [pad_with] * shift_by + l[:-shift_by]

def find_largest_nonzero(a):
    for i, v in reversed(list(enumerate(a))):
        if v != 0:
            return i
    return -1

supnumbers = "⁰¹²³⁴⁵⁶⁷⁸⁹"
supmap = {str(i): supnumbers[i] for i in range(10)}

class IntField:
    """
    Initialize a new galois field with prime *p*. Not passing a prime
    here will give funny results.
    """

    class IntFromField:
        def __init__(self, v, field):
            self.field = field
            if isinstance(v, int):
                v = v % field.p
            else:
                v = v.v
            self.v = v

        def _test_other(self, other):
            if other.field != self.field:
                raise TypeError("Cannot mix different field integers ({} != {})".format(self.field, other.field))

        def __add__(self, other):
            if isinstance(other, int):
                return self.field(self.v + other)
            else:
                self._test_other(other)
                return self.field(self.v + other.v)

        def __sub__(self, other):
            if isinstance(other, int):
                return self.field(self.v - other)
            else:
                self._test_other(other)
                return self.field(self.v - other.v)

        def __mul__(self, other):
            if isinstance(other, int):
                return self.field(self.v * other)
            else:
                self._test_other(other)
                return self.field(self.v * other.v)

        def __floordiv__(self, other):
            if isinstance(other, int):
                return self / self.field(other)
            else:
                self._test_other(other)
                if other.v == 0:
                    raise ZeroDivisionError()
                return self * self.field.find_inverse(other)

        def __eq__(self, other):
            if isinstance(other, int):
                return self.v == other % self.field.p
            else:
                self._test_other(other)
                return self.v == other.v

        def __ne__(self, other):
            return not self == other

        def __str__(self):
            return str(self.v)

        def __repr__(self):
            return "IntFromField({!r}, {!r})".format(self.v, self.field)


    def __init__(self, p):
        self.p = p
        self._inverse_cache = {}

    def find_inverse(self, iff):
        try:
            return self._inverse_cache[iff.v]
        except KeyError:
            v = iff.v
            p = self.p
            for other in range(p):
                if other*v % p == 1:
                    self._inverse_cache[v] = other
                    return self(other)
            raise ValueError("No inverse exists for {} in {}".format(iff.v, self))

    def __str__(self):
        return "ℤ_{}".format(self.p)

    def __call__(self, v):
        if hasattr(v, "__iter__"):
            return map(self, v)
        else:
            return self.IntFromField(v, self)

    def __repr__(self):
        return "IntField({!r})".format(self.p)

class FieldPoly:
    def __init__(self, field, cs):
        self.field = field
        self.cs = list(field(cs))

    def _divmod(self, other):
        field = self.field
        commonlen = max(len(self.cs), len(other.cs))

        cs_lhs = list(self.cs) + [field(0)] * (commonlen - len(self.cs))
        cs_rhs = list(other.cs) + [field(0)] * (commonlen - len(other.cs))

        div_cs = [field(0)]*commonlen

        rhs_degree = find_largest_nonzero(cs_rhs)
        degree = find_largest_nonzero(cs_lhs)
        if degree < rhs_degree:
            return FieldPoly(field, (0,)), FieldPoly(self.field, self.cs)

        while degree >= rhs_degree:
            shift = degree - rhs_degree
            div_cs[shift] += cs_lhs[degree] // cs_rhs[rhs_degree]

            cs_lhs = listsub(cs_lhs, listshift(cs_rhs, shift))
            degree = find_largest_nonzero(cs_lhs)

        return FieldPoly(field, div_cs), FieldPoly(field, cs_lhs)

    def __mod__(self, other):
        return self._divmod(other)[1]

    def __floordiv__(self, other):
        return self._divmod(other)[0]

    def _format_value(self, kc):
        k, c = kc
        if k == 0:
            if c != 0:
                return str(c)
            else:
                return None
        else:
            if c == 0:
                return None
            if k == 1:
                s = "x"
            else:
                exp = "".join(map(lambda x: supmap.get(x), str(k)))
                s = "x{}".format(exp)
            if c != 1:
                s = "{}".format(c)+s
            return s

    def __str__(self):
        s = "+".join(filter(lambda x: x is not None, map(self._format_value, reversed(list(enumerate(self.cs))))))
        if not s:
            return "0"
        return s

