# bring std.math
#
# Math functions. Everything is a static method on Math, e.g. Math.sqrt(2.0).
# Functions that take floats also accept ints; the ones that work on ints only
# start with "i" (iabs, imin, imax, iclamp, isign, ipow).

class Math:
    # constants
    static def pi() -> float:
        return 3.141592653589793

    static def e() -> float:
        return 2.718281828459045

    static def tau() -> float:
        return 6.283185307179586

    # sign, absolute value, extremes
    static def abs(x: float) -> float:
        return __fabs(x)

    static def iabs(x: int) -> int:
        if x < 0:
            return 0 - x
        return x

    static def sign(x: float) -> int:
        if x > 0.0:
            return 1
        if x < 0.0:
            return -1
        return 0

    static def isign(x: int) -> int:
        if x > 0:
            return 1
        if x < 0:
            return -1
        return 0

    static def min(a: float, b: float) -> float:
        if b < a:
            return b
        return a

    static def max(a: float, b: float) -> float:
        if b > a:
            return b
        return a

    static def imin(a: int, b: int) -> int:
        if b < a:
            return b
        return a

    static def imax(a: int, b: int) -> int:
        if b > a:
            return b
        return a

    static def clamp(x: float, lo: float, hi: float) -> float:
        if lo > hi:
            throw new Error("clamp: lo is greater than hi")
        return Math.min(Math.max(x, lo), hi)

    static def iclamp(x: int, lo: int, hi: int) -> int:
        if lo > hi:
            throw new Error("iclamp: lo is greater than hi")
        return Math.imin(Math.imax(x, lo), hi)

    static def lerp(a: float, b: float, t: float) -> float:
        return a + (b - a) * t

    # rounding (the result stays a float; use int(x) to convert)
    static def floor(x: float) -> float:
        return __floor(x)

    static def ceil(x: float) -> float:
        return __ceil(x)

    static def round(x: float) -> float:
        return __round(x)

    static def trunc(x: float) -> float:
        return __trunc(x)

    # powers, roots, logarithms
    static def sqrt(x: float) -> float:
        return __sqrt(x)

    static def cbrt(x: float) -> float:
        if x < 0.0:
            return 0.0 - __pow(0.0 - x, 1.0 / 3.0)
        return __pow(x, 1.0 / 3.0)

    static def pow(x: float, y: float) -> float:
        return __pow(x, y)

    static def hypot(x: float, y: float) -> float:
        return __sqrt(x * x + y * y)

    static def exp(x: float) -> float:
        return __exp(x)

    static def ln(x: float) -> float:
        return __log(x)

    static def log10(x: float) -> float:
        return __log10(x)

    static def log2(x: float) -> float:
        return __log(x) / __log(2.0)

    static def logBase(x: float, base: float) -> float:
        return __log(x) / __log(base)

    # trigonometry (radians)
    static def sin(x: float) -> float:
        return __sin(x)

    static def cos(x: float) -> float:
        return __cos(x)

    static def tan(x: float) -> float:
        return __tan(x)

    static def asin(x: float) -> float:
        return __asin(x)

    static def acos(x: float) -> float:
        return __acos(x)

    static def atan(x: float) -> float:
        return __atan(x)

    static def atan2(y: float, x: float) -> float:
        return __atan2(y, x)

    static def sinh(x: float) -> float:
        return __sinh(x)

    static def cosh(x: float) -> float:
        return __cosh(x)

    static def tanh(x: float) -> float:
        return __tanh(x)

    static def toRadians(deg: float) -> float:
        return deg * 3.141592653589793 / 180.0

    static def toDegrees(rad: float) -> float:
        return rad * 180.0 / 3.141592653589793

    # floating point checks
    static def isNaN(x: float) -> bool:
        return x != x

    static def isInfinite(x: float) -> bool:
        return x - x != 0.0 and x == x

    # integers
    static def ipow(base: int, exp: int) -> int:
        if exp < 0:
            throw new Error("ipow: negative exponent")
        result = 1
        b = base
        n = exp
        while n > 0:
            if n % 2 == 1:
                result = result * b
            b = b * b
            n = n / 2
        return result

    # remainder that takes the sign of the divisor: mod(-1, 5) == 4
    static def mod(a: int, b: int) -> int:
        if b == 0:
            throw new Error("mod: division by zero")
        return ((a % b) + b) % b

    static def gcd(a: int, b: int) -> int:
        x = Math.iabs(a)
        y = Math.iabs(b)
        while y != 0:
            t = x % y
            x = y
            y = t
        return x

    static def lcm(a: int, b: int) -> int:
        if a == 0 or b == 0:
            return 0
        return Math.iabs(a / Math.gcd(a, b) * b)

    static def isqrt(n: int) -> int:
        if n < 0:
            throw new Error("isqrt: negative number")
        r = int(__sqrt(float(n)))
        while r * r > n:
            r -= 1
        while (r + 1) * (r + 1) <= n:
            r += 1
        return r

    static def isPrime(n: int) -> bool:
        if n < 2:
            return false
        if n < 4:
            return true
        if n % 2 == 0:
            return false
        d = 3
        while d * d <= n:
            if n % d == 0:
                return false
            d += 2
        return true

    # 0! .. 20! fit in an int
    static def factorial(n: int) -> int:
        if n < 0 or n > 20:
            throw new Error("factorial: n must be between 0 and 20")
        result = 1
        for i in range(2, n + 1):
            result = result * i
        return result

    static def fib(n: int) -> int:
        if n < 0 or n > 92:
            throw new Error("fib: n must be between 0 and 92")
        a = 0
        b = 1
        for i in range(n):
            t = a + b
            a = b
            b = t
        return a
