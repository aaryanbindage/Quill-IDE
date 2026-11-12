# bring std.console
#
# Printing to the terminal: text without a newline, colours, cursor control and
# reading input. Colours and cursor moves are ANSI escape sequences; Console.init()
# turns them on in the Windows console (modern terminals need nothing).
#
# Colours are numbers: 0..7 normal, 8..15 bright, 16..255 the 256-colour palette
# (see Console.rgb to pick one by red/green/blue). -1 means "leave as is".

class Console:
    # call once at the start of a program that uses colours; harmless everywhere
    static def init():
        __console_init()

    # print text as it is, with no newline added
    static def write(s: str):
        __write(s)

    # print and add a newline (the same as the built-in print for one string)
    static def writeln(s: str):
        __write(s)
        __write("\n")

    static def flush():
        __flush()

    # the escape character that starts every control sequence
    static def esc() -> str:
        s = __str_alloc(1)
        __str_set(s, 0, 27)
        return s

    # ---- colours ----
    static def fg(color: int) -> str:
        if color < 0:
            return ""
        return Console.esc() + "[38;5;" + str(color) + "m"

    static def bg(color: int) -> str:
        if color < 0:
            return ""
        return Console.esc() + "[48;5;" + str(color) + "m"

    static def reset() -> str:
        return Console.esc() + "[0m"

    # the 256-colour palette entry closest to a red/green/blue mix (each 0..255)
    static def rgb(r: int, g: int, b: int) -> int:
        if r < 0:
            r = 0
        if g < 0:
            g = 0
        if b < 0:
            b = 0
        if r > 255:
            r = 255
        if g > 255:
            g = 255
        if b > 255:
            b = 255
        if r == g and g == b:
            # greys have their own ramp, 232..255
            if r < 8:
                return 16
            if r > 248:
                return 231
            return 232 + (r - 8) * 24 / 247
        return 16 + 36 * (r * 5 / 255) + 6 * (g * 5 / 255) + (b * 5 / 255)

    # text in a colour, followed by a reset
    static def paint(text: str, color: int) -> str:
        return Console.fg(color) + text + Console.reset()

    static def paintOn(text: str, color: int, background: int) -> str:
        return Console.fg(color) + Console.bg(background) + text + Console.reset()

    static def bold(text: str) -> str:
        return Console.esc() + "[1m" + text + Console.reset()

    static def dim(text: str) -> str:
        return Console.esc() + "[2m" + text + Console.reset()

    static def underline(text: str) -> str:
        return Console.esc() + "[4m" + text + Console.reset()

    static def invert(text: str) -> str:
        return Console.esc() + "[7m" + text + Console.reset()

    # named colours
    static def black() -> int:
        return 0

    static def red() -> int:
        return 1

    static def green() -> int:
        return 2

    static def yellow() -> int:
        return 3

    static def blue() -> int:
        return 4

    static def magenta() -> int:
        return 5

    static def cyan() -> int:
        return 6

    static def white() -> int:
        return 7

    static def gray() -> int:
        return 8

    # ---- screen and cursor ----
    static def clear():
        __write(Console.esc() + "[2J" + Console.esc() + "[H")

    static def clearLine():
        __write(Console.esc() + "[2K\r")

    # 1-based, like the terminal itself: row 1, column 1 is the top left
    static def moveTo(row: int, col: int):
        __write(Console.esc() + "[" + str(row) + ";" + str(col) + "H")

    static def hideCursor():
        __write(Console.esc() + "[?25l")

    static def showCursor():
        __write(Console.esc() + "[?25h")

    # switch to a separate screen that disappears when you leave (like a full-screen app)
    static def enterScreen():
        __write(Console.esc() + "[?1049h")

    static def leaveScreen():
        __write(Console.esc() + "[?1049l")

    static def sleep(ms: int):
        __flush()
        __sleep_ms(ms)

    # ---- input ----
    # one line from standard input, without the newline, or null at the end of the input
    static def readLine() -> str:
        __flush()
        bytes = new List[int]()
        sawEnd = false
        while true:
            c = __getc()
            if c < 0:
                sawEnd = true
                break
            if c == 10:
                break
            if c != 13:
                bytes.add(c)
        n = bytes.size()
        if sawEnd and n == 0:
            return null
        s = __str_alloc(n)
        for i in range(n):
            b = bytes.get(i)
            if b == 0:
                b = 63
            __str_set(s, i, b)
        return s

    # show a prompt, then read a line (null at the end of the input)
    static def ask(prompt: str) -> str:
        __write(prompt)
        return Console.readLine()
