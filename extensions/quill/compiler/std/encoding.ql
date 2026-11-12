# bring std.encoding
#
# Text forms for binary data: Hex and Base64. Both work on List[int] of bytes.
# Decoding malformed input throws an Error.

class Hex:
    static def encode(bs: List[int]) -> str:
        digits = "0123456789abcdef"
        n = bs.size()
        s = __str_alloc(n * 2)
        for i in range(n):
            b = bs.get(i) & 255
            __str_set(s, i * 2, __str_byte(digits, b >> 4))
            __str_set(s, i * 2 + 1, __str_byte(digits, b & 15))
        return s

    static def nibble(c: int) -> int:
        if c >= 48 and c <= 57:
            return c - 48
        if c >= 97 and c <= 102:
            return c - 87
        if c >= 65 and c <= 70:
            return c - 55
        throw new Error("decode: invalid hex digit")

    static def decode(s: str) -> List[int]:
        n = len(s)
        if n % 2 != 0:
            throw new Error("decode: hex text must have an even length")
        out = new List[int]()
        for i in range(n / 2):
            hi = Hex.nibble(__str_byte(s, i * 2))
            lo = Hex.nibble(__str_byte(s, i * 2 + 1))
            out.add((hi << 4) | lo)
        return out

class Base64:
    static def alphabet() -> str:
        return "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

    static def encode(bs: List[int]) -> str:
        abc = Base64.alphabet()
        n = bs.size()
        groups = (n + 2) / 3
        s = __str_alloc(groups * 4)
        for g in range(groups):
            i = g * 3
            b0 = bs.get(i) & 255
            b1 = 0
            b2 = 0
            if i + 1 < n:
                b1 = bs.get(i + 1) & 255
            if i + 2 < n:
                b2 = bs.get(i + 2) & 255
            v = (b0 << 16) | (b1 << 8) | b2
            __str_set(s, g * 4, __str_byte(abc, (v >> 18) & 63))
            __str_set(s, g * 4 + 1, __str_byte(abc, (v >> 12) & 63))
            if i + 1 < n:
                __str_set(s, g * 4 + 2, __str_byte(abc, (v >> 6) & 63))
            else:
                __str_set(s, g * 4 + 2, 61)
            if i + 2 < n:
                __str_set(s, g * 4 + 3, __str_byte(abc, v & 63))
            else:
                __str_set(s, g * 4 + 3, 61)
        return s

    static def sextet(c: int) -> int:
        if c >= 65 and c <= 90:
            return c - 65
        if c >= 97 and c <= 122:
            return c - 71
        if c >= 48 and c <= 57:
            return c + 4
        if c == 43:
            return 62
        if c == 47:
            return 63
        throw new Error("decode: invalid base64 character")

    static def decode(s: str) -> List[int]:
        n = len(s)
        if n % 4 != 0:
            throw new Error("decode: base64 text must be a multiple of 4 characters")
        out = new List[int]()
        for g in range(n / 4):
            i = g * 4
            c2 = __str_byte(s, i + 2)
            c3 = __str_byte(s, i + 3)
            pad = 0
            if c3 == 61:
                pad = 1
            if c2 == 61:
                pad = 2
                if c3 != 61:
                    throw new Error("decode: malformed base64 padding")
            if pad > 0 and g != n / 4 - 1:
                throw new Error("decode: padding in the middle of base64 text")
            v = (Base64.sextet(__str_byte(s, i)) << 18) | (Base64.sextet(__str_byte(s, i + 1)) << 12)
            if pad < 2:
                v = v | (Base64.sextet(c2) << 6)
            if pad < 1:
                v = v | Base64.sextet(c3)
            out.add((v >> 16) & 255)
            if pad < 2:
                out.add((v >> 8) & 255)
            if pad < 1:
                out.add(v & 255)
        return out
