# bring std.crypto
#
# The safe, high-level interface. Reach for this before std.cipher.
#
#   token = Crypto.encrypt("correct horse", "attack at dawn")
#   text  = Crypto.decrypt("correct horse", token)      # throws Error on a wrong password or tampering
#
#   box   = Crypto.seal(key, bytes)                      # AES-256-CTR + HMAC-SHA256, encrypt-then-MAC
#   bytes = Crypto.open(key, box)
#
# Random numbers come from the operating system's secure source (unlike
# std.random, which is a reproducible generator).

bring std.text
bring std.encoding
bring std.hash
bring std.cipher

class Crypto:
    # n bytes from the operating system's secure random source
    static def randomBytes(n: int) -> List[int]:
        if n < 0:
            throw new Error("randomBytes: n must not be negative")
        out = new List[int]()
        while out.size() < n:
            word = __entropy()
            for i in range(8):
                if out.size() < n:
                    out.add((word >>> (8 * i)) & 255)
        return out

    # a random number 0 <= x < bound, without modulo bias
    static def randomInt(bound: int) -> int:
        if bound <= 0:
            throw new Error("randomInt: bound must be positive")
        limit = 0x7FFFFFFFFFFFFFFF - (0x7FFFFFFFFFFFFFFF % bound)
        x = __entropy() & 0x7FFFFFFFFFFFFFFF
        while x >= limit:
            x = __entropy() & 0x7FFFFFFFFFFFFFFF
        return x % bound

    # a fresh random key of `bytes` bytes (16, 24 or 32 suit AES)
    static def generateKey(bytes: int) -> List[int]:
        return Crypto.randomBytes(bytes)

    # compares in time that does not depend on where the first difference is
    static def equals(a: List[int], b: List[int]) -> bool:
        diff = a.size() ^ b.size()
        n = a.size()
        if b.size() < n:
            n = b.size()
        for i in range(n):
            diff = diff | (a.get(i) ^ b.get(i))
        return diff == 0

    static def subkey(key: List[int], label: str) -> List[int]:
        return Hash.hmacSha256(key, Text.bytes(label))

    # encrypts and authenticates: iv (16) + ciphertext + tag (32). Any key length works.
    static def seal(key: List[int], data: List[int]) -> List[int]:
        if key.size() < 16:
            throw new Error("seal: the key must be at least 16 bytes")
        iv = Crypto.randomBytes(16)
        ct = Cipher.aesCtr(Crypto.subkey(key, "quill-enc"), iv, data)
        box = iv.copy()
        box.addAll(ct)
        box.addAll(Hash.hmacSha256(Crypto.subkey(key, "quill-mac"), box))
        return box

    static def open(key: List[int], box: List[int]) -> List[int]:
        if key.size() < 16:
            throw new Error("open: the key must be at least 16 bytes")
        if box.size() < 48:
            throw new Error("open: the data is too short to be sealed")
        body = Cipher.slice(box, 0, box.size() - 32)
        tag = Cipher.slice(box, box.size() - 32, 32)
        expected = Hash.hmacSha256(Crypto.subkey(key, "quill-mac"), body)
        if not Crypto.equals(tag, expected):
            throw new Error("open: authentication failed (wrong key or tampered data)")
        iv = Cipher.slice(body, 0, 16)
        ct = Cipher.slice(body, 16, body.size() - 16)
        return Cipher.aesCtr(Crypto.subkey(key, "quill-enc"), iv, ct)

    static def iterations() -> int:
        return 20000

    # password-based: returns text (base64) holding a version byte, the PBKDF2 iteration
    # count, a random salt and the sealed message
    static def encrypt(password: str, text: str) -> str:
        return Crypto.encryptWith(password, text, Crypto.iterations())

    # the same with a chosen PBKDF2 iteration count (more is slower and safer)
    static def encryptWith(password: str, text: str, n: int) -> str:
        salt = Crypto.randomBytes(16)
        key = Hash.pbkdf2(password, salt, n, 32)
        out = [1, (n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255]
        out.addAll(salt)
        out.addAll(Crypto.seal(key, Text.bytes(text)))
        return Base64.encode(out)

    static def decrypt(password: str, token: str) -> str:
        raw = Base64.decode(token)
        if raw.size() < 5 + 16 + 48 or raw.get(0) != 1:
            throw new Error("decrypt: not a token made by Crypto.encrypt")
        n = (raw.get(1) << 24) | (raw.get(2) << 16) | (raw.get(3) << 8) | raw.get(4)
        if n < 1 or n > 5000000:
            throw new Error("decrypt: unreasonable iteration count")
        key = Hash.pbkdf2(password, Cipher.slice(raw, 5, 16), n, 32)
        plain = Crypto.open(key, Cipher.slice(raw, 21, raw.size() - 21))
        return Text.fromBytes(plain)

    # a salted, slow hash of a password for storing: "iterations$salt$hash" (salt and
    # hash in hex). The iteration count is stored, so it can be raised later.
    static def hashPassword(password: str) -> str:
        return Crypto.hashPasswordWith(password, Crypto.iterations())

    static def hashPasswordWith(password: str, n: int) -> str:
        salt = Crypto.randomBytes(16)
        return str(n) + "$" + Hex.encode(salt) + "$" + Hex.encode(Hash.pbkdf2(password, salt, n, 32))

    # false for a wrong password or for text that is not a stored hash
    static def checkPassword(password: str, stored: str) -> bool:
        parts = Crypto.splitDollar(stored)
        if parts.size() != 3:
            return false
        n = Crypto.parseInt(parts.get(0))
        if n < 1 or n > 5000000:
            return false
        salt = Hex.decode(parts.get(1))
        want = Hex.decode(parts.get(2))
        return Crypto.equals(Hash.pbkdf2(password, salt, n, want.size()), want)

    # -1 when s is not a plain non-negative number
    static def parseInt(s: str) -> int:
        n = len(s)
        if n == 0 or n > 9:
            return -1
        v = 0
        for i in range(n):
            c = __str_byte(s, i)
            if c < 48 or c > 57:
                return -1
            v = v * 10 + (c - 48)
        return v

    static def splitDollar(s: str) -> List[str]:
        out = new List[str]()
        start = 0
        n = len(s)
        for i in range(n):
            if __str_byte(s, i) == 36:
                out.add(Crypto.part(s, start, i))
                start = i + 1
        out.add(Crypto.part(s, start, n))
        return out

    static def part(s: str, from: int, to: int) -> str:
        bs = new List[int]()
        for i in range(from, to):
            bs.add(__str_byte(s, i))
        return Text.fromBytes(bs)
