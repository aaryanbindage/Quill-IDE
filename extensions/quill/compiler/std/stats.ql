# bring std.stats
#
# Statistics over lists. The float functions take a List[float]; the ones whose
# names start with "i" take a List[int]. Empty lists throw an Error.

bring std.math

class Stats:
    static def sum(xs: List[float]) -> float:
        total = 0.0
        for x in xs:
            total += x
        return total

    static def mean(xs: List[float]) -> float:
        if xs.isEmpty():
            throw new Error("mean of an empty list")
        return Stats.sum(xs) / float(xs.size())

    static def median(xs: List[float]) -> float:
        if xs.isEmpty():
            throw new Error("median of an empty list")
        s = xs.sorted()
        n = s.size()
        if n % 2 == 1:
            return s.get(n / 2)
        return (s.get(n / 2 - 1) + s.get(n / 2)) / 2.0

    # population variance and standard deviation
    static def variance(xs: List[float]) -> float:
        m = Stats.mean(xs)
        total = 0.0
        for x in xs:
            total += (x - m) * (x - m)
        return total / float(xs.size())

    static def stddev(xs: List[float]) -> float:
        return Math.sqrt(Stats.variance(xs))

    static def range(xs: List[float]) -> float:
        if xs.isEmpty():
            throw new Error("range of an empty list")
        return xs.max() - xs.min()

    static def isum(xs: List[int]) -> int:
        total = 0
        for x in xs:
            total += x
        return total

    static def imean(xs: List[int]) -> float:
        if xs.isEmpty():
            throw new Error("mean of an empty list")
        return float(Stats.isum(xs)) / float(xs.size())

    static def imedian(xs: List[int]) -> float:
        if xs.isEmpty():
            throw new Error("median of an empty list")
        s = xs.sorted()
        n = s.size()
        if n % 2 == 1:
            return float(s.get(n / 2))
        return float(s.get(n / 2 - 1) + s.get(n / 2)) / 2.0
