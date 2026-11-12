# The methods of int, float, bool and str.
#
# This file is loaded automatically; you never bring it. When the compiler sees
# `s.upper()` on a value of a basic type it calls the static method of the same
# name on the matching class below, passing the value as the first argument.
# The class names start with two underscores so they cannot clash with yours.

class __Str:
    private static def need(s: str):
        if s == null:
            throw new Error("cannot call a method on a null string")

    private static def isSpace(c: int) -> bool:
        return c == 32 or c == 9 or c == 10 or c == 13 or c == 11 or c == 12

    private static def fromList(bs: List[int]) -> str:
        n = bs.size()
        r = __str_alloc(n)
        for i in range(n):
            r_b = bs.get(i)
            if r_b == 0:
                r_b = 63
            __str_set(r, i, r_b)
        return r

    private static def slice(s: str, a: int, b: int) -> str:
        r = __str_alloc(b - a)
        for i in range(b - a):
            __str_set(r, i, __str_byte(s, a + i))
        return r

    private static def matchAt(s: str, sub: str, at: int) -> bool:
        if at < 0 or at + len(sub) > len(s):
            return false
        for i in range(len(sub)):
            if __str_byte(s, at + i) != __str_byte(sub, i):
                return false
        return true

    static def length(s: str) -> int:
        __Str.need(s)
        return len(s)

    static def isEmpty(s: str) -> bool:
        __Str.need(s)
        return len(s) == 0

    static def upper(s: str) -> str:
        __Str.need(s)
        r = __str_alloc(len(s))
        for i in range(len(s)):
            c = __str_byte(s, i)
            if c >= 97 and c <= 122:
                c = c - 32
            __str_set(r, i, c)
        return r

    static def lower(s: str) -> str:
        __Str.need(s)
        r = __str_alloc(len(s))
        for i in range(len(s)):
            c = __str_byte(s, i)
            if c >= 65 and c <= 90:
                c = c + 32
            __str_set(r, i, c)
        return r

    # first letter in capitals, the rest unchanged
    static def capitalize(s: str) -> str:
        __Str.need(s)
        r = __str_alloc(len(s))
        for i in range(len(s)):
            c = __str_byte(s, i)
            if i == 0 and c >= 97 and c <= 122:
                c = c - 32
            __str_set(r, i, c)
        return r

    # without spaces, tabs and newlines at both ends
    static def trim(s: str) -> str:
        __Str.need(s)
        a = 0
        b = len(s)
        while a < b and __Str.isSpace(__str_byte(s, a)):
            a = a + 1
        while b > a and __Str.isSpace(__str_byte(s, b - 1)):
            b = b - 1
        return __Str.slice(s, a, b)

    # the position of the first occurrence of sub, or -1
    static def indexOf(s: str, sub: str) -> int:
        __Str.need(s)
        __Str.need(sub)
        for i in range(len(s) - len(sub) + 1):
            if __Str.matchAt(s, sub, i):
                return i
        return -1

    static def contains(s: str, sub: str) -> bool:
        return __Str.indexOf(s, sub) >= 0

    static def startsWith(s: str, prefix: str) -> bool:
        __Str.need(s)
        __Str.need(prefix)
        return __Str.matchAt(s, prefix, 0)

    static def endsWith(s: str, suffix: str) -> bool:
        __Str.need(s)
        __Str.need(suffix)
        return __Str.matchAt(s, suffix, len(s) - len(suffix))

    # how many times sub occurs (without overlapping)
    static def count(s: str, sub: str) -> int:
        __Str.need(s)
        __Str.need(sub)
        if len(sub) == 0:
            throw new Error("count: the text to look for is empty")
        n = 0
        i = 0
        while i + len(sub) <= len(s):
            if __Str.matchAt(s, sub, i):
                n = n + 1
                i = i + len(sub)
            else:
                i = i + 1
        return n

    # the part from start up to, but not including, end
    static def substring(s: str, start: int, end: int) -> str:
        __Str.need(s)
        if start < 0 or end > len(s) or start > end:
            throw new Error("substring: " + str(start) + ".." + str(end) + " is outside a string of length " + str(len(s)))
        return __Str.slice(s, start, end)

    static def charAt(s: str, i: int) -> str:
        __Str.need(s)
        if i < 0 or i >= len(s):
            throw new Error("charAt: index " + str(i) + " is outside a string of length " + str(len(s)))
        return __Str.slice(s, i, i + 1)

    # the byte value (0..255) at position i
    static def byteAt(s: str, i: int) -> int:
        __Str.need(s)
        if i < 0 or i >= len(s):
            throw new Error("byteAt: index " + str(i) + " is outside a string of length " + str(len(s)))
        return __str_byte(s, i)

    static def replace(s: str, old: str, replacement: str) -> str:
        __Str.need(s)
        __Str.need(old)
        __Str.need(replacement)
        if len(old) == 0:
            throw new Error("replace: the text to replace is empty")
        out = ""
        i = 0
        while i < len(s):
            if __Str.matchAt(s, old, i):
                out = out + replacement
                i = i + len(old)
            else:
                out = out + __Str.slice(s, i, i + 1)
                i = i + 1
        return out

    # the pieces between occurrences of sep; an empty sep gives one piece per character
    static def split(s: str, sep: str) -> List[str]:
        __Str.need(s)
        __Str.need(sep)
        parts = new List[str]()
        if len(sep) == 0:
            for i in range(len(s)):
                parts.add(__Str.slice(s, i, i + 1))
            return parts
        start = 0
        i = 0
        while i + len(sep) <= len(s):
            if __Str.matchAt(s, sep, i):
                parts.add(__Str.slice(s, start, i))
                i = i + len(sep)
                start = i
            else:
                i = i + 1
        parts.add(__Str.slice(s, start, len(s)))
        return parts

    static def lines(s: str) -> List[str]:
        return __Str.split(s, "\n")

    # the items joined with this string between them: ", ".join(names)
    static def join(sep: str, items: List[str]) -> str:
        __Str.need(sep)
        out = ""
        for i in range(items.size()):
            if i > 0:
                out = out + sep
            out = out + items.get(i)
        return out

    static def repeat(s: str, n: int) -> str:
        __Str.need(s)
        if n < 0:
            throw new Error("repeat: the count cannot be negative")
        out = ""
        for i in range(n):
            out = out + s
        return out

    static def reverse(s: str) -> str:
        __Str.need(s)
        n = len(s)
        r = __str_alloc(n)
        for i in range(n):
            __str_set(r, i, __str_byte(s, n - 1 - i))
        return r

    # pad with ch (its first character) on the left / right up to width
    static def padLeft(s: str, width: int, ch: str) -> str:
        __Str.need(s)
        out = s
        while len(out) < width:
            out = ch + out
        return out

    static def padRight(s: str, width: int, ch: str) -> str:
        __Str.need(s)
        out = s
        while len(out) < width:
            out = out + ch
        return out

    # an integer written in decimal, with an optional leading - or +; anything else throws
    static def toInt(s: str) -> int:
        __Str.need(s)
        t = __Str.trim(s)
        n = len(t)
        i = 0
        neg = false
        if n > 0 and (__str_byte(t, 0) == 45 or __str_byte(t, 0) == 43):
            neg = __str_byte(t, 0) == 45
            i = 1
        if i >= n:
            throw new Error("toInt: \"" + s + "\" is not a number")
        v = 0
        while i < n:
            c = __str_byte(t, i)
            if c < 48 or c > 57:
                throw new Error("toInt: \"" + s + "\" is not a number")
            v = v * 10 + (c - 48)
            i = i + 1
        if neg:
            return 0 - v
        return v

    # a number such as 3, -2.5 or 1.5e3. The result is very close to the exact value, but
    # the last digit is not always correctly rounded.
    static def toFloat(s: str) -> float:
        __Str.need(s)
        t = __Str.trim(s)
        n = len(t)
        i = 0
        neg = false
        if n > 0 and (__str_byte(t, 0) == 45 or __str_byte(t, 0) == 43):
            neg = __str_byte(t, 0) == 45
            i = 1
        v = 0.0
        digits = 0
        while i < n and __str_byte(t, i) >= 48 and __str_byte(t, i) <= 57:
            v = v * 10.0 + (__str_byte(t, i) - 48)
            digits = digits + 1
            i = i + 1
        if i < n and __str_byte(t, i) == 46:
            i = i + 1
            scale = 0.1
            while i < n and __str_byte(t, i) >= 48 and __str_byte(t, i) <= 57:
                v = v + (__str_byte(t, i) - 48) * scale
                scale = scale / 10.0
                digits = digits + 1
                i = i + 1
        if digits == 0:
            throw new Error("toFloat: \"" + s + "\" is not a number")
        if i < n and (__str_byte(t, i) == 101 or __str_byte(t, i) == 69):
            i = i + 1
            eneg = false
            if i < n and (__str_byte(t, i) == 45 or __str_byte(t, i) == 43):
                eneg = __str_byte(t, i) == 45
                i = i + 1
            if i >= n:
                throw new Error("toFloat: \"" + s + "\" is not a number")
            e = 0
            while i < n and __str_byte(t, i) >= 48 and __str_byte(t, i) <= 57:
                e = e * 10 + (__str_byte(t, i) - 48)
                i = i + 1
                if e > 400:
                    e = 400
            for k in range(e):
                if eneg:
                    v = v / 10.0
                else:
                    v = v * 10.0
        if i < n:
            throw new Error("toFloat: \"" + s + "\" is not a number")
        if neg:
            return 0.0 - v
        return v

    static def toString(s: str) -> str:
        __Str.need(s)
        return s


class __Int:
    static def toString(i: int) -> str:
        return str(i)

    static def toFloat(i: int) -> float:
        return float(i)

    static def abs(i: int) -> int:
        if i < 0:
            return 0 - i
        return i

    static def sign(i: int) -> int:
        if i < 0:
            return -1
        if i > 0:
            return 1
        return 0

    static def min(i: int, other: int) -> int:
        if other < i:
            return other
        return i

    static def max(i: int, other: int) -> int:
        if other > i:
            return other
        return i

    static def clamp(i: int, lo: int, hi: int) -> int:
        if lo > hi:
            throw new Error("clamp: lo is greater than hi")
        if i < lo:
            return lo
        if i > hi:
            return hi
        return i

    static def isEven(i: int) -> bool:
        return i % 2 == 0

    static def isOdd(i: int) -> bool:
        return i % 2 != 0

    # i to the power e (wraps on overflow like other int arithmetic)
    static def pow(i: int, e: int) -> int:
        if e < 0:
            throw new Error("pow: the exponent cannot be negative")
        result = 1
        base = i
        while e > 0:
            if e % 2 == 1:
                result = result * base
            base = base * base
            e = e / 2
        return result

    # hexadecimal digits (negative numbers show their 64-bit pattern)
    static def toHex(i: int) -> str:
        return __Int.digits(i, 4, 15)

    static def toBinary(i: int) -> str:
        return __Int.digits(i, 1, 1)

    private static def digits(i: int, bits: int, mask: int) -> str:
        if i == 0:
            return "0"
        chars = "0123456789abcdef"
        bs = new List[int]()
        v = i
        while v != 0:
            bs.add(__str_byte(chars, v & mask))
            v = v >>> bits
        bs.reverse()
        n = bs.size()
        r = __str_alloc(n)
        for k in range(n):
            __str_set(r, k, bs.get(k))
        return r


class __Float:
    static def toString(x: float) -> str:
        return str(x)

    static def isNaN(x: float) -> bool:
        return x != x

    static def abs(x: float) -> float:
        if x < 0.0:
            return 0.0 - x
        return x

    static def sign(x: float) -> int:
        if x < 0.0:
            return -1
        if x > 0.0:
            return 1
        return 0

    static def min(x: float, other: float) -> float:
        if other < x:
            return other
        return x

    static def max(x: float, other: float) -> float:
        if other > x:
            return other
        return x

    static def clamp(x: float, lo: float, hi: float) -> float:
        if lo > hi:
            throw new Error("clamp: lo is greater than hi")
        if x < lo:
            return lo
        if x > hi:
            return hi
        return x

    # the whole-number part, rounding toward zero; throws for NaN or a value too large for int
    static def toInt(x: float) -> int:
        if x != x or x >= 9223372036854775807.0 or x <= -9223372036854775807.0:
            throw new Error("toInt: " + str(x) + " does not fit in an int")
        return int(x)

    # the nearest whole numbers, as ints
    static def floor(x: float) -> int:
        i = __Float.toInt(x)
        if float(i) > x:
            return i - 1
        return i

    static def ceil(x: float) -> int:
        i = __Float.toInt(x)
        if float(i) < x:
            return i + 1
        return i

    # halves round away from zero
    static def round(x: float) -> int:
        if x < 0.0:
            return 0 - __Float.floor(0.5 - x)
        return __Float.floor(x + 0.5)


class __Bool:
    static def toString(b: bool) -> str:
        return str(b)
