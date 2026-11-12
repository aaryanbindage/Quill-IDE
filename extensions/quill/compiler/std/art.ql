# bring std.art
#
# Text art for the terminal: a Canvas to draw on (points, lines, rectangles, circles,
# text, flood fill) that prints in colour, a block-letter Banner, and a few helpers
# (Art.shade, Art.rainbow, Art.boxed). Everything is plain text, so it also works when
# the output is redirected to a file.
#
# Coordinates start at 0,0 in the top left; x grows to the right and y grows downward.
# Colours are the numbers described in std.console (-1 means "no colour").

bring std.console

class Canvas:
    private w: int
    private h: int
    private cells: List[int]
    private fgs: List[int]
    private bgs: List[int]

    def init(self, width: int, height: int):
        if width < 1 or height < 1:
            throw new Error("Canvas: width and height must be at least 1")
        if width * height > 4000000:
            throw new Error("Canvas: that is too big")
        self.w = width
        self.h = height
        self.cells = new List[int]()
        self.fgs = new List[int]()
        self.bgs = new List[int]()
        for i in range(width * height):
            self.cells.add(32)
            self.fgs.add(-1)
            self.bgs.add(-1)

    def width(self) -> int:
        return self.w

    def height(self) -> int:
        return self.h

    def inside(self, x: int, y: int) -> bool:
        return x >= 0 and y >= 0 and x < self.w and y < self.h

    # empty the canvas (spaces, no colour)
    def clear(self):
        for i in range(self.w * self.h):
            self.cells.set(i, 32)
            self.fgs.set(i, -1)
            self.bgs.set(i, -1)

    # put one character, with a colour, at x,y. Points outside the canvas are ignored,
    # so shapes may hang over the edge. Only the first character of ch is used.
    def plot(self, x: int, y: int, ch: str, color: int):
        if not self.inside(x, y):
            return
        i = y * self.w + x
        if len(ch) == 0:
            self.cells.set(i, 32)
        else:
            self.cells.set(i, __str_byte(ch, 0))
        self.fgs.set(i, color)

    # colour the background of one cell
    def paintBackground(self, x: int, y: int, color: int):
        if self.inside(x, y):
            self.bgs.set(y * self.w + x, color)

    # the character at x,y (a space outside the canvas)
    def get(self, x: int, y: int) -> str:
        if not self.inside(x, y):
            return " "
        return Art.chr(self.cells.get(y * self.w + x))

    def colorAt(self, x: int, y: int) -> int:
        if not self.inside(x, y):
            return -1
        return self.fgs.get(y * self.w + x)

    def fill(self, ch: str, color: int):
        for y in range(self.h):
            for x in range(self.w):
                self.plot(x, y, ch, color)

    # a straight line between two points
    def line(self, x0: int, y0: int, x1: int, y1: int, ch: str, color: int):
        dx = x1 - x0
        if dx < 0:
            dx = 0 - dx
        dy = y1 - y0
        if dy < 0:
            dy = 0 - dy
        sx = 1
        if x0 > x1:
            sx = -1
        sy = 1
        if y0 > y1:
            sy = -1
        err = dx - dy
        x = x0
        y = y0
        while true:
            self.plot(x, y, ch, color)
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 > 0 - dy:
                err = err - dy
                x = x + sx
            if e2 < dx:
                err = err + dx
                y = y + sy

    # the outline of a rectangle with its top left corner at x,y
    def rect(self, x: int, y: int, width: int, height: int, ch: str, color: int):
        if width < 1 or height < 1:
            return
        self.line(x, y, x + width - 1, y, ch, color)
        self.line(x, y + height - 1, x + width - 1, y + height - 1, ch, color)
        self.line(x, y, x, y + height - 1, ch, color)
        self.line(x + width - 1, y, x + width - 1, y + height - 1, ch, color)

    def fillRect(self, x: int, y: int, width: int, height: int, ch: str, color: int):
        for j in range(height):
            for i in range(width):
                self.plot(x + i, y + j, ch, color)

    # a rectangle drawn with + - | corners and edges (works in every terminal)
    def frame(self, x: int, y: int, width: int, height: int, color: int):
        if width < 2 or height < 2:
            return
        self.line(x, y, x + width - 1, y, "-", color)
        self.line(x, y + height - 1, x + width - 1, y + height - 1, "-", color)
        self.line(x, y, x, y + height - 1, "|", color)
        self.line(x + width - 1, y, x + width - 1, y + height - 1, "|", color)
        self.plot(x, y, "+", color)
        self.plot(x + width - 1, y, "+", color)
        self.plot(x, y + height - 1, "+", color)
        self.plot(x + width - 1, y + height - 1, "+", color)

    # the outline of a circle around cx,cy. Terminal cells are about twice as tall as
    # they are wide, so a circle of radius r looks round if you use ellipse(cx, cy, 2*r, r).
    def circle(self, cx: int, cy: int, r: int, ch: str, color: int):
        self.ellipse(cx, cy, r, r, ch, color)

    def fillCircle(self, cx: int, cy: int, r: int, ch: str, color: int):
        self.fillEllipse(cx, cy, r, r, ch, color)

    def ellipse(self, cx: int, cy: int, rx: int, ry: int, ch: str, color: int):
        if rx < 0 or ry < 0:
            return
        if rx == 0 or ry == 0:
            self.line(cx - rx, cy - ry, cx + rx, cy + ry, ch, color)
            return
        # step around the outline in many small angles using integer arithmetic
        steps = (rx + ry) * 8
        px = cx + rx
        py = cy
        for i in range(1, steps + 1):
            t = Art.sinCos(i * 360 / steps)
            nx = cx + rx * t.cos() / 1000
            ny = cy + ry * t.sin() / 1000
            self.line(px, py, nx, ny, ch, color)
            px = nx
            py = ny

    def fillEllipse(self, cx: int, cy: int, rx: int, ry: int, ch: str, color: int):
        if rx < 0 or ry < 0:
            return
        if ry == 0:
            self.line(cx - rx, cy, cx + rx, cy, ch, color)
            return
        for j in range(0 - ry, ry + 1):
            # the half width of the ellipse on this row: rx * sqrt(1 - (j/ry)^2)
            span = Art.isqrt((ry * ry - j * j) * rx * rx * 1000000 / (ry * ry)) / 1000
            self.line(cx - span, cy + j, cx + span, cy + j, ch, color)

    # a string written left to right starting at x,y
    def text(self, x: int, y: int, s: str, color: int):
        for i in range(len(s)):
            self.plot(x + i, y, Art.chr(__str_byte(s, i)), color)

    # fill the connected area around x,y that holds the same character
    def floodFill(self, x: int, y: int, ch: str, color: int):
        if not self.inside(x, y) or len(ch) == 0:
            return
        target = self.cells.get(y * self.w + x)
        targetColor = self.fgs.get(y * self.w + x)
        newCode = __str_byte(ch, 0)
        if target == newCode and targetColor == color:
            return
        stack = new List[int]()
        stack.add(y * self.w + x)
        while stack.size() > 0:
            i = stack.pop()
            if self.cells.get(i) != target or self.fgs.get(i) != targetColor:
                continue
            self.cells.set(i, newCode)
            self.fgs.set(i, color)
            cx = i % self.w
            cy = i / self.w
            if cx > 0:
                stack.add(i - 1)
            if cx < self.w - 1:
                stack.add(i + 1)
            if cy > 0:
                stack.add(i - self.w)
            if cy < self.h - 1:
                stack.add(i + self.w)

    # copy another canvas onto this one with its top left corner at x,y; spaces in the
    # copied canvas are left transparent
    def draw(self, other: Canvas, x: int, y: int):
        for j in range(other.height()):
            for i in range(other.width()):
                k = j * other.width() + i
                code = other.cells.get(k)
                if code != 32:
                    self.plot(x + i, y + j, Art.chr(code), other.fgs.get(k))

    # a bar chart: one column per value, scaled so the largest value reaches the top
    def bars(self, values: List[int], ch: str, color: int):
        top = 1
        for v in values:
            if v > top:
                top = v
        for i in range(values.size()):
            if i >= self.w:
                break
            n = values.get(i) * self.h / top
            for j in range(n):
                self.plot(i, self.h - 1 - j, ch, color)

    # the picture as plain text, one line per row, trailing spaces removed
    def toString(self) -> str:
        return self.render(false)

    # the picture; with colour = true the colours are included as escape sequences
    def render(self, colour: bool) -> str:
        out = ""
        for y in range(self.h):
            row = ""
            curFg = -1
            curBg = -1
            last = self.w - 1
            while last >= 0 and self.cells.get(y * self.w + last) == 32 and self.bgs.get(y * self.w + last) < 0:
                last = last - 1
            for x in range(last + 1):
                i = y * self.w + x
                if colour and (self.fgs.get(i) != curFg or self.bgs.get(i) != curBg):
                    if curFg >= 0 or curBg >= 0:
                        row = row + Console.reset()
                    row = row + Console.fg(self.fgs.get(i)) + Console.bg(self.bgs.get(i))
                    curFg = self.fgs.get(i)
                    curBg = self.bgs.get(i)
                row = row + Art.chr(self.cells.get(i))
            if colour and (curFg >= 0 or curBg >= 0):
                row = row + Console.reset()
            out = out + row + "\n"
        return out

    # print the picture, in colour
    def show(self):
        Console.init()
        Console.write(self.render(true))


class SinCos:
    private s: int
    private c: int

    def init(self, s: int, c: int):
        self.s = s
        self.c = c

    # the values are scaled by 1000 (so 1000 means 1.0)
    def sin(self) -> int:
        return self.s

    def cos(self) -> int:
        return self.c


class Art:
    static def chr(code: int) -> str:
        s = __str_alloc(1)
        __str_set(s, 0, code)
        return s

    # integer square root, rounded down
    static def isqrt(n: int) -> int:
        if n <= 0:
            return 0
        x = n
        y = (x + 1) / 2
        while y < x:
            x = y
            y = (x + n / x) / 2
        return x

    # sine and cosine of an angle in degrees, times 1000, from a quarter-wave table
    static def sinCos(degrees: int) -> SinCos:
        d = degrees % 360
        if d < 0:
            d = d + 360
        return new SinCos(Art.sine(d), Art.sine(d + 90))

    static def sine(d: int) -> int:
        d = d % 360
        sign = 1
        if d >= 180:
            sign = -1
            d = d - 180
        if d > 90:
            d = 180 - d
        # 4*d*(180-d) / (40500 - d*(180-d)) is Bhaskara's approximation of sin(d degrees)
        p = d * (180 - d)
        return sign * (4000 * p / (40500 - p))

    # a character for a brightness between 0.0 (blank) and 1.0 (dense), for shading
    static def shade(v: float) -> str:
        ramp = " .:-=+*#%@"
        i = 0
        while i < 9 and v * 10.0 >= i + 1:
            i = i + 1
        return Art.chr(__str_byte(ramp, i))

    # the text with each letter in the next colour of a rainbow
    static def rainbow(text: str) -> str:
        colors = new List[int]()
        colors.add(196)
        colors.add(208)
        colors.add(226)
        colors.add(46)
        colors.add(51)
        colors.add(21)
        colors.add(129)
        out = ""
        n = 0
        for i in range(len(text)):
            c = Art.chr(__str_byte(text, i))
            if c == " ":
                out = out + c
            else:
                out = out + Console.paint(c, colors.get(n % colors.size()))
                n = n + 1
        return out

    # a line of the same character repeated
    static def rule(width: int, ch: str) -> str:
        out = ""
        for i in range(width):
            out = out + ch
        return out

    # lines of text inside a box
    static def boxed(lines: List[str]) -> str:
        widest = 0
        for l in lines:
            if len(l) > widest:
                widest = len(l)
        out = "+" + Art.rule(widest + 2, "-") + "+\n"
        for l in lines:
            out = out + "| " + l + Art.rule(widest - len(l), " ") + " |\n"
        return out + "+" + Art.rule(widest + 2, "-") + "+\n"


# Large letters, five rows tall. Letters, digits, space and ! . - ? : + * / = are
# available; lowercase is shown as capitals and anything else as a question mark.
class Banner:
    private static def keys() -> str:
        return "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 !.-?:+*/="

    private static def glyphs() -> List[str]:
        f = new List[str]()
        f.add(".###.#...#######...##...#")
        f.add("####.#...#####.#...#####.")
        f.add(".#####....#....#.....####")
        f.add("####.#...##...##...#####.")
        f.add("######....####.#....#####")
        f.add("######....####.#....#....")
        f.add(".#####....#..###...#.###.")
        f.add("#...##...#######...##...#")
        f.add("#####..#....#....#..#####")
        f.add("..###...#....#.#..#..##..")
        f.add("#...##..#.###..#..#.#...#")
        f.add("#....#....#....#....#####")
        f.add("#...###.###.#.##...##...#")
        f.add("#...###..##.#.##..###...#")
        f.add(".###.#...##...##...#.###.")
        f.add("####.#...#####.#....#....")
        f.add(".###.#...##.#.##..#..##.#")
        f.add("####.#...#####.#..#.#...#")
        f.add(".#####.....###.....#####.")
        f.add("#####..#....#....#....#..")
        f.add("#...##...##...##...#.###.")
        f.add("#...##...##...#.#.#...#..")
        f.add("#...##...##.#.###.###...#")
        f.add("#...#.#.#...#...#.#.#...#")
        f.add("#...#.#.#...#....#....#..")
        f.add("#####...#...#...#...#####")
        f.add(".###.#..###.#.###..#.###.")
        f.add("..#...##....#....#...###.")
        f.add(".###.#...#..##..#...#####")
        f.add("####.....#.###.....#####.")
        f.add("#..#.#..#.#####...#....#.")
        f.add("######....####.....#####.")
        f.add(".###.#....####.#...#.###.")
        f.add("#####....#...#...#....#..")
        f.add(".###.#...#.###.#...#.###.")
        f.add(".###.#...#.####....#.###.")
        f.add(".........................")
        f.add("..#....#....#.........#..")
        f.add("......................#..")
        f.add("..........#####..........")
        f.add(".###.#...#..##........#..")
        f.add(".......#.........#.......")
        f.add(".......#..#####..#.......")
        f.add(".....#.#.#.###.#.#.#.....")
        f.add("....#...#...#...#...#....")
        f.add(".....#####.....#####.....")
        return f

    # the text as five lines of big letters; `on` and `off` are what the filled and
    # empty dots of each letter are drawn with (one visible character wide)
    static def renderWith(text: str, on: str, off: str) -> str:
        font = Banner.glyphs()
        k = Banner.keys()
        out = ""
        for row in range(5):
            line = ""
            for i in range(len(text)):
                c = __str_byte(text, i)
                if c >= 97 and c <= 122:
                    c = c - 32
                g = 0
                for j in range(len(k)):
                    if __str_byte(k, j) == c:
                        g = j
                        break
                if g == 0 and c != 65:
                    g = Banner.questionMark(k)
                glyph = font.get(g)
                for col in range(5):
                    if __str_byte(glyph, row * 5 + col) == 35:
                        line = line + on
                    else:
                        line = line + off
                line = line + off
            out = out + line + "\n"
        return out

    private static def questionMark(k: str) -> int:
        for j in range(len(k)):
            if __str_byte(k, j) == 63:
                return j
        return 0

    static def render(text: str) -> str:
        return Banner.renderWith(text, "#", " ")

    # print the text in big letters, in a colour
    static def show(text: str, color: int):
        Console.init()
        Console.write(Console.paint(Banner.render(text), color))
