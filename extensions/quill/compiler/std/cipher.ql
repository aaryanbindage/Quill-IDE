# bring std.cipher
#
# Block and stream ciphers over List[int] of bytes.
#
#   Aes             the AES block cipher (128, 192 or 256 bit keys), one block at a time
#   Cipher          ready-made modes: AES-CBC with padding, AES-CTR, ChaCha20, repeating XOR
#
# These give confidentiality only. Nothing here detects tampering; for that use
# std.crypto, whose seal/open add a message authentication code.

bring std.encoding

class Aes:
    private rk: List[int]
    private sbox: List[int]
    private inv: List[int]
    private rounds: int

    def init(self, key: List[int]):
        n = key.size()
        if n != 16 and n != 24 and n != 32:
            throw new Error("Aes: the key must be 16, 24 or 32 bytes")
        sb = Hex.decode("637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b27509832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cfd0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdbe0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9ee1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16")
        iv = new List[int]()
        for i in range(256):
            iv.add(0)
        for i in range(256):
            iv.set(sb.get(i), i)
        self.sbox = sb
        self.inv = iv
        nk = n / 4
        self.rounds = nk + 6
        total = 4 * (self.rounds + 1)
        rk = key.copy()
        rcon = 1
        for i in range(nk, total):
            t0 = rk.get(4 * (i - 1))
            t1 = rk.get(4 * (i - 1) + 1)
            t2 = rk.get(4 * (i - 1) + 2)
            t3 = rk.get(4 * (i - 1) + 3)
            if i % nk == 0:
                n0 = sb.get(t1) ^ rcon
                n1 = sb.get(t2)
                n2 = sb.get(t3)
                n3 = sb.get(t0)
                rcon = Aes.xtime(rcon)
                t0 = n0
                t1 = n1
                t2 = n2
                t3 = n3
            elif nk > 6 and i % nk == 4:
                t0 = sb.get(t0)
                t1 = sb.get(t1)
                t2 = sb.get(t2)
                t3 = sb.get(t3)
            rk.add(rk.get(4 * (i - nk)) ^ t0)
            rk.add(rk.get(4 * (i - nk) + 1) ^ t1)
            rk.add(rk.get(4 * (i - nk) + 2) ^ t2)
            rk.add(rk.get(4 * (i - nk) + 3) ^ t3)
        self.rk = rk

    static def xtime(x: int) -> int:
        r = (x << 1) & 255
        if (x & 128) != 0:
            r = r ^ 27
        return r

    static def gmul(a: int, b: int) -> int:
        p = 0
        x = a
        y = b
        for i in range(8):
            if (y & 1) != 0:
                p = p ^ x
            x = Aes.xtime(x)
            y = y >> 1
        return p

    private def addRoundKey(self, s: List[int], r: int):
        for i in range(16):
            s.set(i, s.get(i) ^ self.rk.get(16 * r + i))

    private def subBytes(self, s: List[int], table: List[int]):
        for i in range(16):
            s.set(i, table.get(s.get(i)))

    static def shiftRows(s: List[int]) -> List[int]:
        t = new List[int]()
        for i in range(16):
            r = i % 4
            c = i / 4
            t.add(s.get(r + 4 * ((c + r) % 4)))
        return t

    static def invShiftRows(s: List[int]) -> List[int]:
        t = new List[int]()
        for i in range(16):
            r = i % 4
            c = i / 4
            t.add(s.get(r + 4 * ((c - r + 4) % 4)))
        return t

    static def mixColumns(s: List[int]):
        for c in range(4):
            a0 = s.get(4 * c)
            a1 = s.get(4 * c + 1)
            a2 = s.get(4 * c + 2)
            a3 = s.get(4 * c + 3)
            s.set(4 * c, Aes.xtime(a0) ^ (Aes.xtime(a1) ^ a1) ^ a2 ^ a3)
            s.set(4 * c + 1, a0 ^ Aes.xtime(a1) ^ (Aes.xtime(a2) ^ a2) ^ a3)
            s.set(4 * c + 2, a0 ^ a1 ^ Aes.xtime(a2) ^ (Aes.xtime(a3) ^ a3))
            s.set(4 * c + 3, (Aes.xtime(a0) ^ a0) ^ a1 ^ a2 ^ Aes.xtime(a3))

    static def invMixColumns(s: List[int]):
        for c in range(4):
            a0 = s.get(4 * c)
            a1 = s.get(4 * c + 1)
            a2 = s.get(4 * c + 2)
            a3 = s.get(4 * c + 3)
            s.set(4 * c, Aes.gmul(a0, 14) ^ Aes.gmul(a1, 11) ^ Aes.gmul(a2, 13) ^ Aes.gmul(a3, 9))
            s.set(4 * c + 1, Aes.gmul(a0, 9) ^ Aes.gmul(a1, 14) ^ Aes.gmul(a2, 11) ^ Aes.gmul(a3, 13))
            s.set(4 * c + 2, Aes.gmul(a0, 13) ^ Aes.gmul(a1, 9) ^ Aes.gmul(a2, 14) ^ Aes.gmul(a3, 11))
            s.set(4 * c + 3, Aes.gmul(a0, 11) ^ Aes.gmul(a1, 13) ^ Aes.gmul(a2, 9) ^ Aes.gmul(a3, 14))

    # encrypts one 16-byte block
    def encryptBlock(self, block: List[int]) -> List[int]:
        if block.size() != 16:
            throw new Error("Aes: a block is 16 bytes")
        s = block.copy()
        self.addRoundKey(s, 0)
        for r in range(1, self.rounds):
            self.subBytes(s, self.sbox)
            s = Aes.shiftRows(s)
            Aes.mixColumns(s)
            self.addRoundKey(s, r)
        self.subBytes(s, self.sbox)
        s = Aes.shiftRows(s)
        self.addRoundKey(s, self.rounds)
        return s

    # decrypts one 16-byte block
    def decryptBlock(self, block: List[int]) -> List[int]:
        if block.size() != 16:
            throw new Error("Aes: a block is 16 bytes")
        s = block.copy()
        self.addRoundKey(s, self.rounds)
        r = self.rounds - 1
        while r >= 1:
            s = Aes.invShiftRows(s)
            self.subBytes(s, self.inv)
            self.addRoundKey(s, r)
            Aes.invMixColumns(s)
            r -= 1
        s = Aes.invShiftRows(s)
        self.subBytes(s, self.inv)
        self.addRoundKey(s, 0)
        return s

class Cipher:
    static def slice(xs: List[int], from: int, count: int) -> List[int]:
        out = new List[int]()
        for i in range(count):
            out.add(xs.get(from + i))
        return out

    # AES in CBC mode with PKCS#7 padding. The iv is 16 bytes and must be unpredictable
    # and different for every message (it is not secret; store it with the ciphertext).
    static def aesCbcEncrypt(key: List[int], iv: List[int], data: List[int]) -> List[int]:
        if iv.size() != 16:
            throw new Error("aesCbcEncrypt: the iv must be 16 bytes")
        aes = new Aes(key)
        buf = data.copy()
        padLen = 16 - data.size() % 16
        for i in range(padLen):
            buf.add(padLen)
        prev = iv.copy()
        out = new List[int]()
        off = 0
        while off < buf.size():
            blk = new List[int]()
            for i in range(16):
                blk.add(buf.get(off + i) ^ prev.get(i))
            prev = aes.encryptBlock(blk)
            out.addAll(prev)
            off += 16
        return out

    static def aesCbcDecrypt(key: List[int], iv: List[int], data: List[int]) -> List[int]:
        if iv.size() != 16:
            throw new Error("aesCbcDecrypt: the iv must be 16 bytes")
        if data.size() == 0 or data.size() % 16 != 0:
            throw new Error("aesCbcDecrypt: ciphertext must be a non-empty multiple of 16 bytes")
        aes = new Aes(key)
        prev = iv.copy()
        out = new List[int]()
        off = 0
        while off < data.size():
            blk = Cipher.slice(data, off, 16)
            plain = aes.decryptBlock(blk)
            for i in range(16):
                out.add(plain.get(i) ^ prev.get(i))
            prev = blk
            off += 16
        padLen = out.get(out.size() - 1)
        ok = padLen >= 1 and padLen <= 16 and padLen <= out.size()
        if ok:
            for i in range(padLen):
                if out.get(out.size() - 1 - i) != padLen:
                    ok = false
        if not ok:
            throw new Error("aesCbcDecrypt: bad padding (wrong key or corrupted data)")
        for i in range(padLen):
            out.pop()
        return out

    # AES in counter mode: a stream cipher, so the same call encrypts and decrypts.
    # `nonce` is the 16-byte initial counter block; never reuse one with the same key.
    static def aesCtr(key: List[int], nonce: List[int], data: List[int]) -> List[int]:
        if nonce.size() != 16:
            throw new Error("aesCtr: the nonce must be 16 bytes")
        aes = new Aes(key)
        counter = nonce.copy()
        out = new List[int]()
        off = 0
        while off < data.size():
            ks = aes.encryptBlock(counter)
            n = data.size() - off
            if n > 16:
                n = 16
            for i in range(n):
                out.add(data.get(off + i) ^ ks.get(i))
            off += 16
            j = 15
            while j >= 0:
                counter.set(j, (counter.get(j) + 1) & 255)
                if counter.get(j) != 0:
                    j = -1
                else:
                    j -= 1
        return out

    static def rotl32(x: int, n: int) -> int:
        return ((x << n) | (x >>> (32 - n))) & 0xFFFFFFFF

    static def quarter(s: List[int], a: int, b: int, c: int, d: int):
        s.set(a, (s.get(a) + s.get(b)) & 0xFFFFFFFF)
        s.set(d, Cipher.rotl32(s.get(d) ^ s.get(a), 16))
        s.set(c, (s.get(c) + s.get(d)) & 0xFFFFFFFF)
        s.set(b, Cipher.rotl32(s.get(b) ^ s.get(c), 12))
        s.set(a, (s.get(a) + s.get(b)) & 0xFFFFFFFF)
        s.set(d, Cipher.rotl32(s.get(d) ^ s.get(a), 8))
        s.set(c, (s.get(c) + s.get(d)) & 0xFFFFFFFF)
        s.set(b, Cipher.rotl32(s.get(b) ^ s.get(c), 7))

    static def littleEndian(xs: List[int], at: int) -> int:
        return xs.get(at) | (xs.get(at + 1) << 8) | (xs.get(at + 2) << 16) | (xs.get(at + 3) << 24)

    # ChaCha20 (RFC 8439): 32-byte key, 12-byte nonce, a block counter to start from
    # (usually 0 or 1). Encrypts and decrypts alike. Never reuse a (key, nonce) pair.
    static def chacha20(key: List[int], nonce: List[int], counter: int, data: List[int]) -> List[int]:
        if key.size() != 32:
            throw new Error("chacha20: the key must be 32 bytes")
        if nonce.size() != 12:
            throw new Error("chacha20: the nonce must be 12 bytes")
        init = [0x61707865, 0x3320646e, 0x79622d32, 0x6b206574]
        for i in range(8):
            init.add(Cipher.littleEndian(key, i * 4))
        init.add(counter & 0xFFFFFFFF)
        for i in range(3):
            init.add(Cipher.littleEndian(nonce, i * 4))
        out = new List[int]()
        off = 0
        while off < data.size():
            s = init.copy()
            for round in range(10):
                Cipher.quarter(s, 0, 4, 8, 12)
                Cipher.quarter(s, 1, 5, 9, 13)
                Cipher.quarter(s, 2, 6, 10, 14)
                Cipher.quarter(s, 3, 7, 11, 15)
                Cipher.quarter(s, 0, 5, 10, 15)
                Cipher.quarter(s, 1, 6, 11, 12)
                Cipher.quarter(s, 2, 7, 8, 13)
                Cipher.quarter(s, 3, 4, 9, 14)
            n = data.size() - off
            if n > 64:
                n = 64
            for i in range(n):
                word = (s.get(i / 4) + init.get(i / 4)) & 0xFFFFFFFF
                out.add(data.get(off + i) ^ ((word >>> (8 * (i % 4))) & 255))
            off += 64
            init.set(12, (init.get(12) + 1) & 0xFFFFFFFF)
        return out

    # XOR with a repeating key. Trivially breakable; useful for masking, not secrecy.
    static def xorBytes(data: List[int], key: List[int]) -> List[int]:
        if key.size() == 0:
            throw new Error("xorBytes: the key is empty")
        out = new List[int]()
        for i in range(data.size()):
            out.add((data.get(i) ^ key.get(i % key.size())) & 255)
        return out
