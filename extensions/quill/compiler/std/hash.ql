# bring std.hash
#
# Message digests and keyed hashes. Inputs and outputs are List[int] of bytes;
# the *Hex methods take and return text. Use std.encoding to print a digest.
#
#   Hash.sha256Hex("abc")
#   Hash.hmacSha256(key, message)
#   Hash.pbkdf2(password, salt, 10000, 32)
#
# SHA-256 and SHA-512 are the standard algorithms. CRC-32 is a checksum, not a
# secure hash. Do not use any of this to store passwords without pbkdf2.

bring std.text
bring std.encoding

class Hash:
    static def rotr32(x: int, n: int) -> int:
        return ((x >>> n) | (x << (32 - n))) & 0xFFFFFFFF

    static def rotr64(x: int, n: int) -> int:
        return (x >>> n) | (x << (64 - n))

    # data + 0x80 + zeros + the bit length, a multiple of `block` bytes in all.
    # `lenBytes` is 8 for SHA-256 and 16 for SHA-512.
    static def pad(data: List[int], block: int, lenBytes: int) -> List[int]:
        msg = data.copy()
        bitlen = data.size() * 8
        msg.add(0x80)
        while msg.size() % block != block - lenBytes:
            msg.add(0)
        for i in range(lenBytes - 8):
            msg.add(0)
        for i in range(8):
            msg.add((bitlen >>> (56 - 8 * i)) & 255)
        return msg

    static def sha256(data: List[int]) -> List[int]:
        k = [0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
            0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
            0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
            0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
            0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
            0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
            0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
            0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2]
        h = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]
        msg = Hash.pad(data, 64, 8)
        w = new List[int]()
        for i in range(64):
            w.add(0)
        off = 0
        while off < msg.size():
            for t in range(16):
                j = off + t * 4
                w.set(t, (msg.get(j) << 24) | (msg.get(j + 1) << 16) | (msg.get(j + 2) << 8) | msg.get(j + 3))
            for t in range(16, 64):
                x = w.get(t - 15)
                y = w.get(t - 2)
                s0 = Hash.rotr32(x, 7) ^ Hash.rotr32(x, 18) ^ (x >>> 3)
                s1 = Hash.rotr32(y, 17) ^ Hash.rotr32(y, 19) ^ (y >>> 10)
                w.set(t, (w.get(t - 16) + s0 + w.get(t - 7) + s1) & 0xFFFFFFFF)
            a = h.get(0)
            b = h.get(1)
            c = h.get(2)
            d = h.get(3)
            e = h.get(4)
            f = h.get(5)
            g = h.get(6)
            hh = h.get(7)
            for t in range(64):
                bigS1 = Hash.rotr32(e, 6) ^ Hash.rotr32(e, 11) ^ Hash.rotr32(e, 25)
                ch = (e & f) ^ (~e & g)
                t1 = (hh + bigS1 + ch + k.get(t) + w.get(t)) & 0xFFFFFFFF
                bigS0 = Hash.rotr32(a, 2) ^ Hash.rotr32(a, 13) ^ Hash.rotr32(a, 22)
                maj = (a & b) ^ (a & c) ^ (b & c)
                t2 = (bigS0 + maj) & 0xFFFFFFFF
                hh = g
                g = f
                f = e
                e = (d + t1) & 0xFFFFFFFF
                d = c
                c = b
                b = a
                a = (t1 + t2) & 0xFFFFFFFF
            h.set(0, (h.get(0) + a) & 0xFFFFFFFF)
            h.set(1, (h.get(1) + b) & 0xFFFFFFFF)
            h.set(2, (h.get(2) + c) & 0xFFFFFFFF)
            h.set(3, (h.get(3) + d) & 0xFFFFFFFF)
            h.set(4, (h.get(4) + e) & 0xFFFFFFFF)
            h.set(5, (h.get(5) + f) & 0xFFFFFFFF)
            h.set(6, (h.get(6) + g) & 0xFFFFFFFF)
            h.set(7, (h.get(7) + hh) & 0xFFFFFFFF)
            off += 64
        out = new List[int]()
        for word in h:
            for i in range(4):
                out.add((word >>> (24 - 8 * i)) & 255)
        return out

    static def sha512(data: List[int]) -> List[int]:
        k = [0x428a2f98d728ae22, 0x7137449123ef65cd, 0xb5c0fbcfec4d3b2f, 0xe9b5dba58189dbbc,
            0x3956c25bf348b538, 0x59f111f1b605d019, 0x923f82a4af194f9b, 0xab1c5ed5da6d8118,
            0xd807aa98a3030242, 0x12835b0145706fbe, 0x243185be4ee4b28c, 0x550c7dc3d5ffb4e2,
            0x72be5d74f27b896f, 0x80deb1fe3b1696b1, 0x9bdc06a725c71235, 0xc19bf174cf692694,
            0xe49b69c19ef14ad2, 0xefbe4786384f25e3, 0x0fc19dc68b8cd5b5, 0x240ca1cc77ac9c65,
            0x2de92c6f592b0275, 0x4a7484aa6ea6e483, 0x5cb0a9dcbd41fbd4, 0x76f988da831153b5,
            0x983e5152ee66dfab, 0xa831c66d2db43210, 0xb00327c898fb213f, 0xbf597fc7beef0ee4,
            0xc6e00bf33da88fc2, 0xd5a79147930aa725, 0x06ca6351e003826f, 0x142929670a0e6e70,
            0x27b70a8546d22ffc, 0x2e1b21385c26c926, 0x4d2c6dfc5ac42aed, 0x53380d139d95b3df,
            0x650a73548baf63de, 0x766a0abb3c77b2a8, 0x81c2c92e47edaee6, 0x92722c851482353b,
            0xa2bfe8a14cf10364, 0xa81a664bbc423001, 0xc24b8b70d0f89791, 0xc76c51a30654be30,
            0xd192e819d6ef5218, 0xd69906245565a910, 0xf40e35855771202a, 0x106aa07032bbd1b8,
            0x19a4c116b8d2d0c8, 0x1e376c085141ab53, 0x2748774cdf8eeb99, 0x34b0bcb5e19b48a8,
            0x391c0cb3c5c95a63, 0x4ed8aa4ae3418acb, 0x5b9cca4f7763e373, 0x682e6ff3d6b2b8a3,
            0x748f82ee5defb2fc, 0x78a5636f43172f60, 0x84c87814a1f0ab72, 0x8cc702081a6439ec,
            0x90befffa23631e28, 0xa4506cebde82bde9, 0xbef9a3f7b2c67915, 0xc67178f2e372532b,
            0xca273eceea26619c, 0xd186b8c721c0c207, 0xeada7dd6cde0eb1e, 0xf57d4f7fee6ed178,
            0x06f067aa72176fba, 0x0a637dc5a2c898a6, 0x113f9804bef90dae, 0x1b710b35131c471b,
            0x28db77f523047d84, 0x32caab7b40c72493, 0x3c9ebe0a15c9bebc, 0x431d67c49c100d4c,
            0x4cc5d4becb3e42b6, 0x597f299cfc657e2a, 0x5fcb6fab3ad6faec, 0x6c44198c4a475817]
        h = [0x6a09e667f3bcc908, 0xbb67ae8584caa73b, 0x3c6ef372fe94f82b, 0xa54ff53a5f1d36f1,
            0x510e527fade682d1, 0x9b05688c2b3e6c1f, 0x1f83d9abfb41bd6b, 0x5be0cd19137e2179]
        msg = Hash.pad(data, 128, 16)
        w = new List[int]()
        for i in range(80):
            w.add(0)
        off = 0
        while off < msg.size():
            for t in range(16):
                j = off + t * 8
                v = 0
                for q in range(8):
                    v = (v << 8) | msg.get(j + q)
                w.set(t, v)
            for t in range(16, 80):
                x = w.get(t - 15)
                y = w.get(t - 2)
                s0 = Hash.rotr64(x, 1) ^ Hash.rotr64(x, 8) ^ (x >>> 7)
                s1 = Hash.rotr64(y, 19) ^ Hash.rotr64(y, 61) ^ (y >>> 6)
                w.set(t, w.get(t - 16) + s0 + w.get(t - 7) + s1)
            a = h.get(0)
            b = h.get(1)
            c = h.get(2)
            d = h.get(3)
            e = h.get(4)
            f = h.get(5)
            g = h.get(6)
            hh = h.get(7)
            for t in range(80):
                bigS1 = Hash.rotr64(e, 14) ^ Hash.rotr64(e, 18) ^ Hash.rotr64(e, 41)
                ch = (e & f) ^ (~e & g)
                t1 = hh + bigS1 + ch + k.get(t) + w.get(t)
                bigS0 = Hash.rotr64(a, 28) ^ Hash.rotr64(a, 34) ^ Hash.rotr64(a, 39)
                maj = (a & b) ^ (a & c) ^ (b & c)
                t2 = bigS0 + maj
                hh = g
                g = f
                f = e
                e = d + t1
                d = c
                c = b
                b = a
                a = t1 + t2
            h.set(0, h.get(0) + a)
            h.set(1, h.get(1) + b)
            h.set(2, h.get(2) + c)
            h.set(3, h.get(3) + d)
            h.set(4, h.get(4) + e)
            h.set(5, h.get(5) + f)
            h.set(6, h.get(6) + g)
            h.set(7, h.get(7) + hh)
            off += 128
        out = new List[int]()
        for word in h:
            for i in range(8):
                out.add((word >>> (56 - 8 * i)) & 255)
        return out

    static def sha256Hex(text: str) -> str:
        return Hex.encode(Hash.sha256(Text.bytes(text)))

    static def sha512Hex(text: str) -> str:
        return Hex.encode(Hash.sha512(Text.bytes(text)))

    # CRC-32 (the checksum used by zip and png), as a number 0 .. 4294967295
    static def crc32(data: List[int]) -> int:
        crc = 0xFFFFFFFF
        for b in data:
            crc = crc ^ (b & 255)
            for i in range(8):
                crc = (crc >>> 1) ^ (0xEDB88320 & (0 - (crc & 1)))
        return (crc ^ 0xFFFFFFFF) & 0xFFFFFFFF

    static def hmacSha256(key: List[int], message: List[int]) -> List[int]:
        k = key
        if k.size() > 64:
            k = Hash.sha256(k)
        inner = new List[int]()
        outer = new List[int]()
        for i in range(64):
            kb = 0
            if i < k.size():
                kb = k.get(i) & 255
            inner.add(kb ^ 0x36)
            outer.add(kb ^ 0x5c)
        inner.addAll(message)
        outer.addAll(Hash.sha256(inner))
        return Hash.sha256(outer)

    # PBKDF2 with HMAC-SHA256: turns a password into `length` key bytes.
    # Slower is safer; 10000 or more iterations for real passwords.
    static def pbkdf2(password: str, salt: List[int], iterations: int, length: int) -> List[int]:
        if iterations < 1:
            throw new Error("pbkdf2: iterations must be at least 1")
        if length < 1:
            throw new Error("pbkdf2: length must be at least 1")
        pw = Text.bytes(password)
        out = new List[int]()
        block = 1
        while out.size() < length:
            seed = salt.copy()
            seed.add((block >>> 24) & 255)
            seed.add((block >>> 16) & 255)
            seed.add((block >>> 8) & 255)
            seed.add(block & 255)
            u = Hash.hmacSha256(pw, seed)
            t = u.copy()
            for it in range(1, iterations):
                u = Hash.hmacSha256(pw, u)
                for i in range(32):
                    t.set(i, t.get(i) ^ u.get(i))
            out.addAll(t)
            block += 1
        while out.size() > length:
            out.pop()
        return out
