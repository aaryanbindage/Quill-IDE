# bring std.text
#
# Strings as bytes. A Quill string is a sequence of bytes that never contains a
# zero byte, so fromBytes rejects 0 and anything outside 1..255. Binary data
# (hashes, ciphertext) should be shown with std.encoding's Hex or Base64.

class Text:
    # the bytes of a string, 0..255 each
    static def bytes(s: str) -> List[int]:
        out = new List[int]()
        n = len(s)
        for i in range(n):
            out.add(__str_byte(s, i))
        return out

    static def fromBytes(bs: List[int]) -> str:
        n = bs.size()
        s = __str_alloc(n)
        for i in range(n):
            b = bs.get(i)
            if b < 1 or b > 255:
                throw new Error("fromBytes: a string cannot hold the byte " + str(b))
            __str_set(s, i, b)
        return s

    static def byteAt(s: str, i: int) -> int:
        if i < 0 or i >= len(s):
            throw new Error("byteAt: index " + str(i) + " is outside the string")
        return __str_byte(s, i)

    # a one-byte string for a code in 1..255
    static def chr(code: int) -> str:
        if code < 1 or code > 255:
            throw new Error("chr: code must be between 1 and 255")
        s = __str_alloc(1)
        __str_set(s, 0, code)
        return s

    static def length(s: str) -> int:
        return len(s)
