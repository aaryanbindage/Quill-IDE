# bring std.native
#
# Memory that C code can read and write, without pointers in sight. A Buffer owns a
# block of native memory, zero filled and one byte longer than asked so that it is
# always NUL terminated. It frees itself when the last reference goes away, so there
# is nothing to free by hand. `quill wrap` uses it for byte arguments; hand-written
# bindings use it the same way:
#
#   buf = Buffer.of(data)                       # copy a List[int] into native memory
#   Lib.checksum(buf.address(), buf.size())     # the address is just an int
#   out = new Buffer(64)                        # room for C to write into
#   n = Lib.fill(out.address(), 64)
#   result = out.toList()

class Buffer:
    private addr: int
    private count: int

    def init(self, size: int):
        if size < 0:
            throw new Error("Buffer: the size must not be negative")
        self.addr = __native_alloc(size)
        self.count = size

    def deinit(self):
        if self.addr != 0:
            __native_free(self.addr)
            self.addr = 0

    static def of(bytes: List[int]) -> Buffer:
        b = new Buffer(bytes.size())
        for i in range(bytes.size()):
            b.set(i, bytes.get(i))
        return b

    # the bytes of a string, plus the terminating zero C expects
    static def ofText(s: str) -> Buffer:
        b = new Buffer(len(s))
        for i in range(len(s)):
            b.set(i, __str_byte(s, i))
        return b

    # the address to hand to a C function that takes a pointer
    def address(self) -> int:
        return self.addr

    def size(self) -> int:
        return self.count

    def get(self, i: int) -> int:
        self.check(i)
        return __native_peek(self.addr, i)

    def set(self, i: int, value: int):
        self.check(i)
        __native_poke(self.addr, i, value & 255)

    private def check(self, i: int):
        if self.addr == 0:
            throw new Error("Buffer: already released")
        if i < 0 or i >= self.count:
            throw new Error("Buffer: index " + str(i) + " is outside 0.." + str(self.count))

    def toList(self) -> List[int]:
        out = new List[int]()
        for i in range(self.count):
            out.add(self.get(i))
        return out

    # the contents up to the first zero byte, as a string
    def toText(self) -> str:
        if self.addr == 0:
            throw new Error("Buffer: already released")
        return __native_cstr(self.addr)

    # free the memory now instead of when the last reference goes away
    def release(self):
        if self.addr != 0:
            __native_free(self.addr)
            self.addr = 0
            self.count = 0
