# bring std.random
#
# A small, seedable pseudo-random generator. The same seed always gives the same
# sequence, on every platform, which makes it good for tests and simulations.
# It is not suitable for anything security related.

class Random:
    private state: int

    def init(self, seed: int):
        self.state = seed * 2862933555777941757 + 3037000493

    # the next value, between 0 and 2147483647
    def next(self) -> int:
        self.state = self.state * 6364136223846793005 + 1442695040888963407
        r = (self.state / 65536) % 2147483648
        if r < 0:
            return 0 - r
        return r

    # 0 <= result < bound
    def nextInt(self, bound: int) -> int:
        if bound <= 0:
            throw new Error("nextInt: bound must be positive")
        return self.next() % bound

    # lo <= result <= hi
    def between(self, lo: int, hi: int) -> int:
        if lo > hi:
            throw new Error("between: lo is greater than hi")
        return lo + self.nextInt(hi - lo + 1)

    # 0.0 <= result < 1.0
    def nextFloat(self) -> float:
        return float(self.next()) / 2147483648.0

    def nextBool(self) -> bool:
        return self.next() % 2 == 0

    # an index into a collection of `size` elements
    def index(self, size: int) -> int:
        return self.nextInt(size)
