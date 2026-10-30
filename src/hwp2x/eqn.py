"""Hangul equation script (한글 수식 편집기) -> tree -> LaTeX / MathML / OMML.

The script language is the one Hangul's equation editor writes, close to
troff EQN:  ``{a+b} over {c}``, ``sqrt {x}``, ``sum from {k=1} to n``,
``left ( x right )``, ``matrix { a & b # c & d }``, ``"text"`` ...

Parsing never fails: anything unrecognised is kept as plain symbols, so an
equation always comes out in some form rather than being dropped.

Hangul inside equations
    * jamo (ㄱ, ㅏ ...) are symbols. For LaTeX they become hangulmath
      commands (profile "tex") or stay as Unicode (profile "htex", whose
      spec treats Hangul in math like Greek letters).
    * syllables (가, 나 ...): a single syllable is a symbol, a run of
      syllables is a word and goes into \\text{}.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from xml.sax.saxutils import escape


# =========================================================================== tree
@dataclass
class Sym:
    text: str                 # display text (Unicode)
    kind: str                 # ident num op rel text hangul func space
    latex: str = ""           # LaTeX override
    style: str = ""           # "" | "rm" | "bold"


@dataclass
class Row:
    items: list = field(default_factory=list)


class Word(Row):
    """Letters typed together (``mc``): a script binds to the last letter."""


@dataclass
class Frac:
    num: object
    den: object
    line: bool = True         # False for "atop"


@dataclass
class Binom:
    n: object
    k: object


@dataclass
class Root:
    body: object
    index: object = None


@dataclass
class Scripts:
    base: object
    sub: object = None
    sup: object = None
    limits: bool = False      # sub/sup drawn under/over (big operators, lim)


@dataclass
class BigOp:
    sym: Sym                  # the operator symbol, e.g. ∑


@dataclass
class Fenced:
    open: str
    close: str
    body: object


@dataclass
class Matrix:
    kind: str                 # matrix pmatrix bmatrix vmatrix cases pile lpile rpile aligned gathered
    rows: list = field(default_factory=list)   # list[list[Row]]


@dataclass
class Accent:
    kind: str                 # bar hat vec dot ddot tilde acute grave check under dyad arch
    body: object


@dataclass
class Text:
    text: str


# =========================================================================== tables
_GREEK_LOWER = {
    "alpha": ("α", r"\alpha"), "beta": ("β", r"\beta"), "gamma": ("γ", r"\gamma"),
    "delta": ("δ", r"\delta"), "epsilon": ("ε", r"\epsilon"), "zeta": ("ζ", r"\zeta"),
    "eta": ("η", r"\eta"), "theta": ("θ", r"\theta"), "iota": ("ι", r"\iota"),
    "kappa": ("κ", r"\kappa"), "lambda": ("λ", r"\lambda"), "mu": ("μ", r"\mu"),
    "nu": ("ν", r"\nu"), "xi": ("ξ", r"\xi"), "omicron": ("ο", "o"), "pi": ("π", r"\pi"),
    "rho": ("ρ", r"\rho"), "sigma": ("σ", r"\sigma"), "tau": ("τ", r"\tau"),
    "upsilon": ("υ", r"\upsilon"), "phi": ("φ", r"\phi"), "chi": ("χ", r"\chi"),
    "psi": ("ψ", r"\psi"), "omega": ("ω", r"\omega"),
    "varepsilon": ("ε", r"\varepsilon"), "vartheta": ("ϑ", r"\vartheta"),
    "varpi": ("ϖ", r"\varpi"), "varrho": ("ϱ", r"\varrho"),
    "varsigma": ("ς", r"\varsigma"), "varphi": ("ϕ", r"\varphi"),
}
_GREEK_UPPER = {
    "ALPHA": ("Α", r"\mathrm{A}"), "BETA": ("Β", r"\mathrm{B}"), "GAMMA": ("Γ", r"\Gamma"),
    "DELTA": ("Δ", r"\Delta"), "EPSILON": ("Ε", r"\mathrm{E}"), "ZETA": ("Ζ", r"\mathrm{Z}"),
    "ETA": ("Η", r"\mathrm{H}"), "THETA": ("Θ", r"\Theta"), "IOTA": ("Ι", r"\mathrm{I}"),
    "KAPPA": ("Κ", r"\mathrm{K}"), "LAMBDA": ("Λ", r"\Lambda"), "MU": ("Μ", r"\mathrm{M}"),
    "NU": ("Ν", r"\mathrm{N}"), "XI": ("Ξ", r"\Xi"), "OMICRON": ("Ο", r"\mathrm{O}"),
    "PI": ("Π", r"\Pi"), "RHO": ("Ρ", r"\mathrm{P}"), "SIGMA": ("Σ", r"\Sigma"),
    "TAU": ("Τ", r"\mathrm{T}"), "UPSILON": ("Υ", r"\Upsilon"), "PHI": ("Φ", r"\Phi"),
    "CHI": ("Χ", r"\mathrm{X}"), "PSI": ("Ψ", r"\Psi"), "OMEGA": ("Ω", r"\Omega"),
}

# name -> (unicode, latex, kind). Looked up case-insensitively.
_SYMBOLS = {
    # relations
    "le": ("≤", r"\le", "rel"), "leq": ("≤", r"\le", "rel"), "ge": ("≥", r"\ge", "rel"),
    "geq": ("≥", r"\ge", "rel"), "ne": ("≠", r"\ne", "rel"), "neq": ("≠", r"\ne", "rel"),
    "approx": ("≈", r"\approx", "rel"), "sim": ("∼", r"\sim", "rel"),
    "simeq": ("≃", r"\simeq", "rel"), "cong": ("≅", r"\cong", "rel"),
    "equiv": ("≡", r"\equiv", "rel"), "propto": ("∝", r"\propto", "rel"),
    "ll": ("≪", r"\ll", "rel"), "gg": ("≫", r"\gg", "rel"),
    "in": ("∈", r"\in", "rel"), "notin": ("∉", r"\notin", "rel"), "ni": ("∋", r"\ni", "rel"),
    "owns": ("∋", r"\ni", "rel"),
    "subset": ("⊂", r"\subset", "rel"), "supset": ("⊃", r"\supset", "rel"),
    "subseteq": ("⊆", r"\subseteq", "rel"), "supseteq": ("⊇", r"\supseteq", "rel"),
    "nsubset": ("⊄", r"\not\subset", "rel"), "perp": ("⊥", r"\perp", "rel"),
    "parallel": ("∥", r"\parallel", "rel"), "vdash": ("⊢", r"\vdash", "rel"),
    "models": ("⊨", r"\models", "rel"), "doteq": ("≐", r"\doteq", "rel"),
    # arrows (Hangul: lower case = single, upper case = double)
    "larrow": ("←", r"\leftarrow", "rel"), "rarrow": ("→", r"\rightarrow", "rel"),
    "lrarrow": ("↔", r"\leftrightarrow", "rel"), "uarrow": ("↑", r"\uparrow", "rel"),
    "darrow": ("↓", r"\downarrow", "rel"), "udarrow": ("↕", r"\updownarrow", "rel"),
    "nearrow": ("↗", r"\nearrow", "rel"), "searrow": ("↘", r"\searrow", "rel"),
    "nwarrow": ("↖", r"\nwarrow", "rel"), "swarrow": ("↙", r"\swarrow", "rel"),
    "mapsto": ("↦", r"\mapsto", "rel"), "hookleft": ("↩", r"\hookleftarrow", "rel"),
    "hookright": ("↪", r"\hookrightarrow", "rel"),
    # binary operators
    "times": ("×", r"\times", "op"), "div": ("÷", r"\div", "op"), "cdot": ("⋅", r"\cdot", "op"),
    "pm": ("±", r"\pm", "op"), "mp": ("∓", r"\mp", "op"), "plusminus": ("±", r"\pm", "op"),
    "minusplus": ("∓", r"\mp", "op"), "circ": ("∘", r"\circ", "op"), "bullet": ("∙", r"\bullet", "op"),
    "oplus": ("⊕", r"\oplus", "op"), "ominus": ("⊖", r"\ominus", "op"),
    "otimes": ("⊗", r"\otimes", "op"), "odot": ("⊙", r"\odot", "op"), "oslash": ("⊘", r"\oslash", "op"),
    "cup": ("∪", r"\cup", "op"), "cap": ("∩", r"\cap", "op"), "union": ("∪", r"\cup", "op"),
    "inter": ("∩", r"\cap", "op"), "setminus": ("∖", r"\setminus", "op"),
    "vee": ("∨", r"\vee", "op"), "wedge": ("∧", r"\wedge", "op"), "lor": ("∨", r"\lor", "op"),
    "land": ("∧", r"\land", "op"), "star": ("⋆", r"\star", "op"), "ast": ("∗", r"\ast", "op"),
    "dagger": ("†", r"\dagger", "op"), "ddagger": ("‡", r"\ddagger", "op"),
    "xor": ("⊻", r"\veebar", "op"), "mod": ("mod", r"\bmod", "func"),
    # misc symbols
    "inf": ("∞", r"\infty", "ident"), "infinity": ("∞", r"\infty", "ident"),
    "infty": ("∞", r"\infty", "ident"),
    "partial": ("∂", r"\partial", "ident"), "nabla": ("∇", r"\nabla", "ident"),
    "forall": ("∀", r"\forall", "op"), "exist": ("∃", r"\exists", "op"), "exists": ("∃", r"\exists", "op"),
    "neg": ("¬", r"\neg", "op"), "not": ("¬", r"\neg", "op"),
    "emptyset": ("∅", r"\emptyset", "ident"), "aleph": ("ℵ", r"\aleph", "ident"),
    "hbar": ("ℏ", r"\hbar", "ident"), "ell": ("ℓ", r"\ell", "ident"), "wp": ("℘", r"\wp", "ident"),
    "re": ("ℜ", r"\Re", "ident"), "im": ("ℑ", r"\Im", "ident"),
    "angle": ("∠", r"\angle", "ident"), "triangle": ("△", r"\triangle", "ident"),
    "therefore": ("∴", r"\therefore", "rel"), "because": ("∵", r"\because", "rel"),
    "deg": ("°", r"^{\circ}", "ident"), "prime": ("′", r"'", "ident"),
    "cdots": ("⋯", r"\cdots", "ident"), "ldots": ("…", r"\ldots", "ident"),
    "vdots": ("⋮", r"\vdots", "ident"), "ddots": ("⋱", r"\ddots", "ident"),
    "dots": ("…", r"\dots", "ident"), "cents": ("¢", r"\textcent", "ident"),
    "top": ("⊤", r"\top", "ident"), "bot": ("⊥", r"\bot", "ident"),
    "diamond": ("◇", r"\diamond", "op"), "box": ("□", r"\square", "ident"),
    "lbrace": ("{", r"\{", "op"), "rbrace": ("}", r"\}", "op"),
    "langle": ("⟨", r"\langle", "op"), "rangle": ("⟩", r"\rangle", "op"),
    "lceil": ("⌈", r"\lceil", "op"), "rceil": ("⌉", r"\rceil", "op"),
    "lfloor": ("⌊", r"\lfloor", "op"), "rfloor": ("⌋", r"\rfloor", "op"),
    "vert": ("|", r"\vert", "op"), "dline": ("‖", r"\|", "op"),
}
# Upper-case double arrows (case-sensitive)
_SYMBOLS_EXACT = {
    "LARROW": ("⇐", r"\Leftarrow", "rel"), "RARROW": ("⇒", r"\Rightarrow", "rel"),
    "LRARROW": ("⇔", r"\Leftrightarrow", "rel"), "UARROW": ("⇑", r"\Uparrow", "rel"),
    "DARROW": ("⇓", r"\Downarrow", "rel"), "UDARROW": ("⇕", r"\Updownarrow", "rel"),
}

_BIGOPS = {
    "sum": ("∑", r"\sum"), "prod": ("∏", r"\prod"), "coprod": ("∐", r"\coprod"),
    "int": ("∫", r"\int"), "dint": ("∬", r"\iint"), "tint": ("∭", r"\iiint"),
    "oint": ("∮", r"\oint"), "odint": ("∯", r"\oiint"), "otint": ("∰", r"\oiiint"),
    "bigcup": ("⋃", r"\bigcup"), "bigcap": ("⋂", r"\bigcap"),
    "bigsqcup": ("⨆", r"\bigsqcup"), "bigoplus": ("⨁", r"\bigoplus"),
    "bigotimes": ("⨂", r"\bigotimes"), "bigodot": ("⨀", r"\bigodot"),
    "biguplus": ("⨄", r"\biguplus"), "bigvee": ("⋁", r"\bigvee"), "bigwedge": ("⋀", r"\bigwedge"),
    "smallsum": ("∑", r"\textstyle\sum"), "smallprod": ("∏", r"\textstyle\prod"),
}
_INTEGRALS = {"int", "dint", "tint", "oint", "odint", "otint"}

# Upright function names. "lim", "max", "min" ... take limits underneath.
_FUNCS = {
    "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan",
    "sinh", "cosh", "tanh", "coth", "log", "ln", "lg", "exp", "det", "dim",
    "gcd", "lcm", "arg", "hom", "ker", "deg_", "Pr", "sup", "lim", "liminf",
    "limsup", "max", "min",
}
_LIMIT_FUNCS = {"lim", "max", "min", "sup", "liminf", "limsup", "det", "gcd", "pr"}
_LATEX_FUNCS = {"sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan",
                "sinh", "cosh", "tanh", "coth", "log", "ln", "lg", "exp", "det", "dim",
                "gcd", "arg", "hom", "ker", "Pr", "sup", "lim", "liminf", "limsup", "max", "min"}

_ACCENTS = {
    "bar": ("¯", r"\overline"), "overline": ("¯", r"\overline"),
    "hat": ("^", r"\widehat"), "widehat": ("^", r"\widehat"), "vec": ("→", r"\overrightarrow"),
    "dot": ("˙", r"\dot"), "ddot": ("¨", r"\ddot"), "tilde": ("~", r"\widetilde"),
    "acute": ("´", r"\acute"), "grave": ("`", r"\grave"), "check": ("ˇ", r"\check"),
    "under": ("_", r"\underline"), "underline": ("_", r"\underline"),
    "dyad": ("↔", r"\overleftrightarrow"), "arch": ("⌢", r"\overset{\frown}"),
}

_MATRICES = {
    "matrix": "matrix", "pmatrix": "pmatrix", "bmatrix": "bmatrix", "dmatrix": "vmatrix",
    "vmatrix": "vmatrix", "cases": "cases", "pile": "pile", "cpile": "pile",
    "lpile": "lpile", "rpile": "rpile", "eqalign": "aligned",
}

_MULTI_OPS = [("<->", "↔", r"\leftrightarrow", "rel"), ("->", "→", r"\to", "rel"),
              ("<-", "←", r"\leftarrow", "rel"), ("<=", "≤", r"\le", "rel"),
              (">=", "≥", r"\ge", "rel"), ("!=", "≠", r"\ne", "rel"),
              ("==", "≡", r"\equiv", "rel"), ("+-", "±", r"\pm", "op"),
              ("-+", "∓", r"\mp", "op"), ("<<", "≪", r"\ll", "rel"), (">>", "≫", r"\gg", "rel"),
              ("...", "…", r"\ldots", "ident"), ("'", "′", "'", "ident")]
_SINGLE = {
    "+": ("+", "+", "op"), "-": ("−", "-", "op"), "=": ("=", "=", "rel"),
    "<": ("<", "<", "rel"), ">": (">", ">", "rel"), "*": ("∗", "*", "op"),
    "/": ("/", "/", "op"), ",": (",", ",", "op"), ";": (";", ";", "op"),
    ":": (":", ":", "rel"), "!": ("!", "!", "op"), "|": ("|", "|", "op"),
    "(": ("(", "(", "op"), ")": (")", ")", "op"), "[": ("[", "[", "op"), "]": ("]", "]", "op"),
    ".": (".", ".", "op"), "?": ("?", "?", "op"), "%": ("%", r"\%", "op"),
    "$": ("$", r"\$", "op"), "@": ("@", "@", "op"), "\\": ("\\", r"\backslash", "op"),
}
_FENCE_WORDS = {"lbrace": "{", "rbrace": "}", "langle": "⟨", "rangle": "⟩", "lceil": "⌈",
                "rceil": "⌉", "lfloor": "⌊", "rfloor": "⌋", "vert": "|", "dline": "‖",
                "||": "‖", "<": "⟨", ">": "⟩", "{": "{", "}": "}"}


def _is_syllable(ch: str) -> bool:
    return "가" <= ch <= "힣"


def _is_jamo(ch: str) -> bool:
    return "ㄱ" <= ch <= "ㆎ" or "ᄀ" <= ch <= "ᇿ"


# =========================================================================== tokenizer
_TOKEN = re.compile(r"""
    (?P<ws>[ \t\r\n]+)
  | (?P<str>"[^"]*"?)
  | (?P<word>[A-Za-z]+)
  | (?P<num>\d+(?:\.\d+)?)
  | (?P<syl>[가-힣]+)
  | (?P<ch>.)
""", re.VERBOSE | re.DOTALL)


def _tokenize(src: str) -> list[tuple[str, str]]:
    toks: list[tuple[str, str]] = []
    i = 0
    while i < len(src):
        matched = False
        for text, _u, _l, _k in _MULTI_OPS:
            if src.startswith(text, i):
                toks.append(("mop", text))
                i += len(text)
                matched = True
                break
        if matched:
            continue
        m = _TOKEN.match(src, i)
        assert m
        kind = m.lastgroup
        val = m.group()
        i = m.end()
        if kind == "ws":
            continue
        if kind == "ch" and val in "{}^_&#`~":
            kind = val
        toks.append((kind, val))
    return toks


# =========================================================================== parser
class _Parser:
    _STOP = {"}", "&", "#"}
    _STOP_WORDS = {"right", "from", "to", "of", "over", "atop", "choose"}

    def __init__(self, src: str):
        self.toks = _tokenize(src)
        self.i = 0
        self.style = ""

    # -- helpers
    def peek(self, k: int = 0):
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else (None, None)

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def peek_word(self) -> str:
        kind, val = self.peek()
        return val.lower() if kind == "word" else ""

    # -- grammar
    def parse(self):
        """Top level: may hold & alignment and # line breaks."""
        rows = self._table_rows(top=True)
        if len(rows) == 1 and len(rows[0]) == 1:
            return rows[0][0]
        has_amp = any(len(r) > 1 for r in rows)
        return Matrix("aligned" if has_amp else "gathered", rows)

    def _table_rows(self, top: bool = False) -> list[list[Row]]:
        rows: list[list[Row]] = [[Row()]]
        while True:
            kind, _ = self.peek()
            if kind is None:
                break
            if kind == "}":
                if top:          # stray closing brace: keep it visible, carry on
                    self.take()
                    rows[-1][-1].items.append(Sym("}", "op", r"\}"))
                    continue
                break
            if kind == "&":
                self.take()
                rows[-1].append(Row())
                continue
            if kind == "#":
                self.take()
                rows.append([Row()])
                continue
            rows[-1][-1].items.extend(self._seq().items)
        return rows

    def _seq(self) -> Row:
        row = Row()
        while True:
            kind, val = self.peek()
            if kind is None or kind in self._STOP:
                break
            if kind == "word" and val.lower() in ("right",):
                break
            if kind == "word" and val.lower() in ("from", "to", "of") and self._in_limits:
                break
            item = self._item()
            if item is not None:
                row.items.append(item)
        return row

    _in_limits = False

    def _item(self):
        base = self._scripted()
        while True:
            w = self.peek_word()
            if w in ("over", "atop"):
                self.take()
                den = self._scripted()
                base = Frac(base, den if den is not None else Row(), line=(w == "over"))
            elif w == "choose":
                self.take()
                k = self._scripted()
                base = Binom(base, k if k is not None else Row())
            else:
                return base

    def _scripted(self):
        base = self._atom()
        if base is None:
            return None
        sub = sup = None
        while True:
            kind, val = self.peek()
            w = val.lower() if kind == "word" else ""
            if kind == "^" or w == "sup":
                self.take()
                sup = self._atom_or_empty()
            elif kind == "_" or w == "sub":
                self.take()
                sub = self._atom_or_empty()
            else:
                break
        if sub is None and sup is None:
            return base
        if isinstance(base, Word) and base.items:
            *head, last = base.items
            return Row(head + [Scripts(last, sub, sup)])
        limits = isinstance(base, BigOp) and base.sym.text not in "∫∬∭∮∯∰"
        if isinstance(base, Sym) and base.kind == "func" and base.text.lower() in _LIMIT_FUNCS:
            limits = True
        return Scripts(base, sub, sup, limits)

    def _atom_or_empty(self):
        a = self._atom()
        return a if a is not None else Row()

    def _group(self) -> Row:
        """``{ ... }``; the opening brace is already consumed."""
        saved_style, saved_lim = self.style, self._in_limits
        self._in_limits = False
        rows = self._table_rows()
        self.style, self._in_limits = saved_style, saved_lim
        if self.peek()[0] == "}":
            self.take()
        if len(rows) == 1 and len(rows[0]) == 1:
            return rows[0][0]
        # a # or & inside plain braces: render as a stacked pile
        return Row([Matrix("pile", rows)])

    def _limits_arg(self):
        saved = self._in_limits
        self._in_limits = True
        a = self._scripted()
        self._in_limits = saved
        return a if a is not None else Row()

    def _atom(self):
        kind, val = self.peek()
        if kind is None or kind in self._STOP:
            return None
        if kind == "{":
            self.take()
            return self._group()
        if kind in ("^", "_"):        # script with no base: attach to empty
            return Row()
        self.take()
        if kind == "`":
            return Sym(" ", "space", r"\,")
        if kind == "~":
            return Sym(" ", "space", r"\ ")
        if kind == "str":
            return Text(val.strip('"'))
        if kind == "num":
            return Sym(val, "num", val, self.style)
        if kind == "syl":
            return Sym(val, "hangul")
        if kind == "mop":
            for text, u, l, k in _MULTI_OPS:
                if text == val:
                    return Sym(u, k, l)
        if kind == "word":
            return self._word(val)
        # single characters
        if val in _SINGLE:
            u, l, k = _SINGLE[val]
            return Sym(u, k, l)
        if _is_jamo(val):
            return Sym(val, "hangul")
        return Sym(val, "ident" if val.isalpha() else "op", "", self.style)

    def _word(self, word: str):
        low = word.lower()
        if word in _GREEK_UPPER and word.isupper():
            u, l = _GREEK_UPPER[word]
            return Sym(u, "ident", l, "rm")
        if low in _GREEK_LOWER and word.islower():
            u, l = _GREEK_LOWER[low]
            return Sym(u, "ident", l, self.style)
        if word in _SYMBOLS_EXACT:
            u, l, k = _SYMBOLS_EXACT[word]
            return Sym(u, k, l)
        if low in ("rm", "it", "bold", "bf"):
            self.style = {"rm": "rm", "it": "", "bold": "bold", "bf": "bold"}[low]
            return Row()   # style switch occupies no space
        if low in ("sqrt", "root"):
            return self._root()
        if low in _ACCENTS:
            body = self._atom_or_empty()
            return Accent(low if low != "overline" else "bar", body)
        if low in _MATRICES:
            return self._matrix(_MATRICES[low])
        if low == "left":
            return self._fenced()
        if low in _BIGOPS:
            u, l = _BIGOPS[low]
            return self._limits(BigOp(Sym(u, "op", l)))
        if low in _FUNCS or low == "pr":
            name = "Pr" if low == "pr" else low
            return self._limits(Sym(name, "func", ""))
        if low in _SYMBOLS:
            u, l, k = _SYMBOLS[low]
            return Sym(u, k, l)
        if low in ("from", "to", "of", "right", "over", "atop", "choose", "sup", "sub"):
            return Sym(word, "ident", "", self.style)       # dangling keyword: keep visible
        # plain letters: a, xy, dx ...
        if len(word) == 1:
            return Sym(word, "ident", "", self.style)
        return Word([Sym(c, "ident", "", self.style) for c in word])

    def _limits(self, op):
        lo = hi = None
        while True:
            w = self.peek_word()
            if w == "from":
                self.take()
                lo = self._limits_arg()
            elif w == "to":
                self.take()
                hi = self._limits_arg()
            else:
                break
        if lo is None and hi is None:
            return op
        limits = not (isinstance(op, BigOp) and op.sym.text in "∫∬∭∮∯∰")
        return Scripts(op, lo, hi, limits)

    def _root(self):
        first = self._atom_or_empty()
        if self.peek_word() == "of":
            self.take()
            body = self._atom_or_empty()
            return Root(body, first)
        return Root(first)

    def _matrix(self, kind: str):
        if self.peek()[0] != "{":
            return Sym(kind, "ident")
        self.take()
        saved = self._in_limits
        self._in_limits = False
        rows = self._table_rows()
        self._in_limits = saved
        if self.peek()[0] == "}":
            self.take()
        return Matrix(kind, rows)

    def _delim(self) -> str:
        kind, val = self.peek()
        if kind is None:
            return ""
        if kind == "word" and val.lower() in _FENCE_WORDS:
            self.take()
            return _FENCE_WORDS[val.lower()]
        if kind == "mop" and val in ("<<", ">>"):
            return ""
        if kind in ("{", "}"):
            self.take()
            return val
        if kind == "ch" and val in "()[]|<>.":
            self.take()
            return {"<": "⟨", ">": "⟩", ".": ""}.get(val, val)
        if kind == "ch" and val == "\\":
            self.take()
            return ""
        return ""

    def _fenced(self):
        open_ = self._delim()
        if open_ == "|" and self.peek() == ("ch", "|"):
            self.take()
            open_ = "‖"
        body = Row()
        while True:
            kind, val = self.peek()
            if kind is None:
                break
            if kind == "word" and val.lower() == "right":
                break
            if kind in ("&", "#"):            # alignment inside a fence: treat as pile
                rows = [[body]]
                while self.peek()[0] in ("&", "#"):
                    sep = self.take()[0]
                    if sep == "#":
                        rows.append([Row()])
                    else:
                        rows[-1].append(Row())
                    rows[-1][-1].items.extend(self._seq().items)
                body = Row([Matrix("pile", rows)])
                continue
            if kind == "}":
                break
            body.items.extend(self._seq().items)
        close = ""
        if self.peek_word() == "right":
            self.take()
            close = self._delim()
            if close == "|" and self.peek() == ("ch", "|"):
                self.take()
                close = "‖"
        return Fenced(open_, close, body)


def parse(script: str):
    """Parse a Hangul equation script into a tree. Never raises."""
    try:
        return _Parser(script or "").parse()
    except Exception:  # pragma: no cover - defensive: keep the text
        return Text(script)


# =========================================================================== LaTeX
_JAMO_TEX = {
    "ㄱ": r"\giug", "ㄴ": r"\niun", "ㄷ": r"\diud", "ㄹ": r"\liul", "ㅁ": r"\mium",
    "ㅂ": r"\biub", "ㅅ": r"\sius", "ㅇ": r"\iung", "ㅈ": r"\jiuj", "ㅊ": r"\ciuc",
    "ㅋ": r"\kiuk", "ㅌ": r"\tiut", "ㅍ": r"\piup", "ㅎ": r"\hiuh",
    "ㄲ": r"\ggiug", "ㄸ": r"\ddiud", "ㅃ": r"\bbiub", "ㅆ": r"\ssius", "ㅉ": r"\jjiuj",
    "ㅏ": r"\hangulsym{ah}", "ㅑ": r"\hangulsym{yah}", "ㅓ": r"\hangulsym{eoh}",
    "ㅕ": r"\hangulsym{yeoh}", "ㅗ": r"\hangulsym{oh}", "ㅛ": r"\hangulsym{yoh}",
    "ㅜ": r"\hangulsym{uh}", "ㅠ": r"\hangulsym{yuh}", "ㅡ": r"\hangulsym{euh}",
    "ㅣ": r"\hangulsym{ih}", "ㅐ": r"\hangulsym{aeh}", "ㅒ": r"\hangulsym{yaeh}",
    "ㅔ": r"\hangulsym{eh}", "ㅖ": r"\hangulsym{yeh}", "ㅘ": r"\hangulsym{uah}",
    "ㅙ": r"\hangulsym{uaeh}", "ㅚ": r"\hangulsym{oeh}", "ㅝ": r"\hangulsym{ueoh}",
    "ㅞ": r"\hangulsym{ueh}", "ㅟ": r"\hangulsym{uih}", "ㅢ": r"\hangulsym{euih}",
}
_TEX_TEXT_ESC = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$", "&": r"\&",
                 "#": r"\#", "%": r"\%", "_": r"\_", "^": r"\^{}", "~": r"\~{}"}
_FENCE_TEX = {"(": "(", ")": ")", "[": "[", "]": "]", "{": r"\{", "}": r"\}", "|": "|",
              "‖": r"\|", "⟨": r"\langle", "⟩": r"\rangle", "⌈": r"\lceil", "⌉": r"\rceil",
              "⌊": r"\lfloor", "⌋": r"\rfloor", "": "."}


def tex_text(s: str) -> str:
    return "".join(_TEX_TEXT_ESC.get(c, c) for c in s)


class _Latex:
    def __init__(self, profile: str):
        self.profile = profile          # "tex" | "htex" | "md"
        self.uses_hangulmath = False

    def emit(self, node) -> str:
        out = self._node(node)
        return re.sub(r"\s+", " ", out).strip()

    def _join(self, parts: list[str]) -> str:
        out = ""
        for p in parts:
            if not p:
                continue
            if out and re.search(r"\\[A-Za-z]+$", out) and re.match(r"[A-Za-z]", p):
                out += " "
            out += p
        return out

    def _arg(self, node) -> str:
        return "{" + self._node(node) + "}"

    def _node(self, n) -> str:
        if n is None:
            return ""
        if isinstance(n, Row):
            return self._row(n.items)
        if isinstance(n, Sym):
            return self._sym(n)
        if isinstance(n, Text):
            return r"\text{" + tex_text(n.text) + "}"
        if isinstance(n, Frac):
            if n.line:
                return r"\frac" + self._arg(n.num) + self._arg(n.den)
            return r"\genfrac{}{}{0pt}{}" + self._arg(n.num) + self._arg(n.den)
        if isinstance(n, Binom):
            return r"\binom" + self._arg(n.n) + self._arg(n.k)
        if isinstance(n, Root):
            idx = "[" + self._node(n.index) + "]" if n.index is not None else ""
            return r"\sqrt" + idx + self._arg(n.body)
        if isinstance(n, BigOp):
            return n.sym.latex
        if isinstance(n, Scripts):
            base = self._node(n.base)
            if isinstance(n.base, (Frac, Binom, Root, Scripts, Accent, Fenced)) or \
                    (isinstance(n.base, Row) and len(n.base.items) != 1):
                base = "{" + base + "}"
            if n.limits and isinstance(n.base, Sym) and n.base.kind == "func" and n.base.text.lower() not in _LATEX_FUNCS:
                base = r"\operatorname*{" + n.base.text + "}"
            out = base
            if n.sub is not None:
                out += "_" + self._arg(n.sub)
            if n.sup is not None:
                out += "^" + self._arg(n.sup)
            return out
        if isinstance(n, Fenced):
            o, c = _FENCE_TEX.get(n.open, "."), _FENCE_TEX.get(n.close, ".")
            return r"\left" + o + " " + self._node(n.body) + r" \right" + c
        if isinstance(n, Accent):
            _u, cmd = _ACCENTS[n.kind]
            return cmd + self._arg(n.body)
        if isinstance(n, Matrix):
            return self._matrix(n)
        return ""

    def _row(self, items: list) -> str:
        parts: list[str] = []
        i = 0
        while i < len(items):
            it = items[i]
            parts.append(self._node(it))
            i += 1
        return self._join(parts)

    def _sym(self, s: Sym) -> str:
        if s.kind == "hangul":
            return self._hangul(s.text)
        if s.kind == "space":
            return s.latex
        if s.kind == "func":
            if s.text.lower() in _LATEX_FUNCS or s.text in _LATEX_FUNCS:
                return "\\" + (s.text if s.text in _LATEX_FUNCS else s.text.lower())
            if s.latex:
                return s.latex
            return r"\operatorname{" + s.text + "}"
        out = s.latex or s.text
        if not s.latex and s.kind == "ident" and len(s.text) == 1 and not s.text.isascii():
            out = s.text
        if s.style == "rm" and s.kind in ("ident",) and re.fullmatch(r"[A-Za-z]+|\\[a-z]+", out):
            return r"\mathrm{" + out + "}"
        if s.style == "bold" and s.kind in ("ident", "num"):
            return r"\mathbf{" + out + "}"
        return out

    def _hangul(self, text: str) -> str:
        if self.profile == "md":           # MathJax/KaTeX: keep every Hangul run as text
            return r"\text{" + text + "}"
        parts = []
        if all(_is_jamo(c) for c in text):
            for c in text:
                if self.profile == "tex" and c in _JAMO_TEX:
                    self.uses_hangulmath = True
                    parts.append(_JAMO_TEX[c])
                else:
                    parts.append(c)
            return self._join(parts)
        if len(text) == 1:
            return text if self.profile == "htex" else r"\text{" + text + "}"
        return r"\text{" + text + "}"

    def _matrix(self, m: Matrix) -> str:
        body = r" \\ ".join(" & ".join(self._node(c) for c in row) for row in m.rows)
        k = m.kind
        if k == "cases":
            return r"\begin{cases} " + body + r" \end{cases}"
        if k in ("matrix", "pmatrix", "bmatrix", "vmatrix"):
            return "\\begin{%s} %s \\end{%s}" % (k, body, k)
        if k in ("aligned", "gathered"):
            return "\\begin{%s} %s \\end{%s}" % (k, body, k)
        ncol = max((len(r) for r in m.rows), default=1)
        align = {"pile": "c", "lpile": "l", "rpile": "r"}.get(k, "c")
        return r"\begin{array}{" + align * ncol + "} " + body + r" \end{array}"


def to_latex(node, profile: str = "tex") -> tuple[str, bool]:
    """Return (latex, uses_hangulmath)."""
    e = _Latex(profile)
    return e.emit(node), e.uses_hangulmath


# =========================================================================== MathML
_FENCE_MML = {"": ""}


class _MathML:
    def node(self, n) -> str:
        if n is None:
            return "<mrow/>"
        if isinstance(n, Row):
            if len(n.items) == 1:
                return self.node(n.items[0])
            return "<mrow>" + "".join(self.node(i) for i in n.items) + "</mrow>"
        if isinstance(n, Sym):
            return self.sym(n)
        if isinstance(n, Text):
            return "<mtext>" + escape(n.text) + "</mtext>"
        if isinstance(n, Frac):
            lt = "" if n.line else ' linethickness="0"'
            return f"<mfrac{lt}>{self.node(n.num)}{self.node(n.den)}</mfrac>"
        if isinstance(n, Binom):
            return ('<mrow><mo>(</mo><mfrac linethickness="0">' + self.node(n.n) + self.node(n.k)
                    + "</mfrac><mo>)</mo></mrow>")
        if isinstance(n, Root):
            if n.index is not None:
                return f"<mroot>{self.node(n.body)}{self.node(n.index)}</mroot>"
            return f"<msqrt>{self.node(n.body)}</msqrt>"
        if isinstance(n, BigOp):
            return f'<mo largeop="true">{escape(n.sym.text)}</mo>'
        if isinstance(n, Scripts):
            base = self.node(n.base)
            if n.limits:
                if n.sub is not None and n.sup is not None:
                    return f"<munderover>{base}{self.node(n.sub)}{self.node(n.sup)}</munderover>"
                if n.sub is not None:
                    return f"<munder>{base}{self.node(n.sub)}</munder>"
                return f"<mover>{base}{self.node(n.sup)}</mover>"
            if n.sub is not None and n.sup is not None:
                return f"<msubsup>{base}{self.node(n.sub)}{self.node(n.sup)}</msubsup>"
            if n.sub is not None:
                return f"<msub>{base}{self.node(n.sub)}</msub>"
            return f"<msup>{base}{self.node(n.sup)}</msup>"
        if isinstance(n, Fenced):
            o = f'<mo fence="true" stretchy="true">{escape(n.open)}</mo>' if n.open else ""
            c = f'<mo fence="true" stretchy="true">{escape(n.close)}</mo>' if n.close else ""
            return f"<mrow>{o}{self.node(n.body)}{c}</mrow>"
        if isinstance(n, Accent):
            ch = _ACCENTS[n.kind][0]
            if n.kind in ("under", "underline"):
                return f'<munder accentunder="true">{self.node(n.body)}<mo>_</mo></munder>'
            if n.kind == "bar":
                ch = "‾"
            if n.kind == "arch":
                ch = "⏜"
            return f'<mover accent="true">{self.node(n.body)}<mo stretchy="true">{escape(ch)}</mo></mover>'
        if isinstance(n, Matrix):
            return self.matrix(n)
        return "<mrow/>"

    def sym(self, s: Sym) -> str:
        t = escape(s.text)
        if s.kind == "num":
            return f"<mn>{t}</mn>"
        if s.kind in ("op", "rel"):
            return f"<mo>{t}</mo>"
        if s.kind == "space":
            return '<mspace width="0.25em"/>' if s.latex == r"\," else '<mspace width="0.5em"/>'
        if s.kind == "func":
            return f'<mi mathvariant="normal">{t}</mi>' if len(s.text) == 1 else f"<mi>{t}</mi>"
        if s.kind == "hangul":
            if len(s.text) == 1:
                return f'<mi mathvariant="normal">{t}</mi>'
            return f"<mtext>{t}</mtext>"
        if s.style == "rm" or (len(s.text) == 1 and not s.text.isascii() and not ("α" <= s.text <= "ω")):
            return f'<mi mathvariant="normal">{t}</mi>'
        if s.style == "bold":
            return f'<mi mathvariant="bold">{t}</mi>'
        return f"<mi>{t}</mi>"

    def matrix(self, m: Matrix) -> str:
        align = {"lpile": "left", "rpile": "right", "cases": "left", "aligned": "right left"}.get(m.kind, "center")
        rows = "".join("<mtr>" + "".join(f"<mtd>{self.node(c)}</mtd>" for c in r) + "</mtr>" for r in m.rows)
        table = f'<mtable columnalign="{align}">{rows}</mtable>'
        fences = {"pmatrix": ("(", ")"), "bmatrix": ("[", "]"), "vmatrix": ("|", "|"), "cases": ("{", "")}
        if m.kind in fences:
            o, c = fences[m.kind]
            co = f"<mo>{c}</mo>" if c else ""
            return f"<mrow><mo>{escape(o)}</mo>{table}{co}</mrow>"
        return table


def to_mathml(node, display: bool = False) -> str:
    inner = _MathML().node(node)
    d = ' display="block"' if display else ""
    return f'<math xmlns="http://www.w3.org/1998/Math/MathML"{d}>{inner}</math>'


# =========================================================================== OMML
class _Omml:
    def run(self, text: str, upright: bool = False) -> str:
        rpr = '<m:rPr><m:sty m:val="p"/></m:rPr>' if upright else ""
        return f'<m:r>{rpr}<w:rPr><w:rFonts w:ascii="Cambria Math" w:hAnsi="Cambria Math"/></w:rPr><m:t xml:space="preserve">{escape(text)}</m:t></m:r>'

    def e(self, n) -> str:
        return "<m:e>" + self.node(n) + "</m:e>"

    def node(self, n) -> str:
        if n is None:
            return ""
        if isinstance(n, Row):
            return "".join(self.node(i) for i in n.items)
        if isinstance(n, Sym):
            upright = n.kind in ("func", "num", "op", "rel", "hangul") or n.style == "rm"
            if n.kind == "space":
                return self.run(" ")
            return self.run(n.text, upright)
        if isinstance(n, Text):
            return self.run(n.text, True)
        if isinstance(n, Frac):
            typ = "" if n.line else '<m:fPr><m:type m:val="noBar"/></m:fPr>'
            return f"<m:f>{typ}<m:num>{self.node(n.num)}</m:num><m:den>{self.node(n.den)}</m:den></m:f>"
        if isinstance(n, Binom):
            return ('<m:d><m:dPr><m:begChr m:val="("/><m:endChr m:val=")"/></m:dPr><m:e><m:f><m:fPr><m:type m:val="noBar"/></m:fPr>'
                    f"<m:num>{self.node(n.n)}</m:num><m:den>{self.node(n.k)}</m:den></m:f></m:e></m:d>")
        if isinstance(n, Root):
            if n.index is None:
                return f'<m:rad><m:radPr><m:degHide m:val="1"/></m:radPr><m:deg/>{self.e(n.body)}</m:rad>'
            return f"<m:rad><m:deg>{self.node(n.index)}</m:deg>{self.e(n.body)}</m:rad>"
        if isinstance(n, BigOp):
            return f'<m:nary><m:naryPr><m:chr m:val="{escape(n.sym.text)}"/><m:subHide m:val="1"/><m:supHide m:val="1"/></m:naryPr><m:sub/><m:sup/><m:e/></m:nary>'
        if isinstance(n, Scripts):
            return self.scripts(n)
        if isinstance(n, Fenced):
            return (f'<m:d><m:dPr><m:begChr m:val="{escape(n.open)}"/><m:endChr m:val="{escape(n.close)}"/></m:dPr>'
                    f"{self.e(n.body)}</m:d>")
        if isinstance(n, Accent):
            if n.kind in ("under", "underline"):
                return f'<m:bar><m:barPr><m:pos m:val="bot"/></m:barPr>{self.e(n.body)}</m:bar>'
            if n.kind == "bar":
                return f'<m:bar><m:barPr><m:pos m:val="top"/></m:barPr>{self.e(n.body)}</m:bar>'
            ch = {"hat": "̂", "vec": "⃗", "dot": "̇", "ddot": "̈", "tilde": "̃",
                  "acute": "́", "grave": "̀", "check": "̌", "dyad": "⃡", "arch": "̑"}.get(n.kind, "̂")
            return f'<m:acc><m:accPr><m:chr m:val="{ch}"/></m:accPr>{self.e(n.body)}</m:acc>'
        if isinstance(n, Matrix):
            return self.matrix(n)
        return ""

    def scripts(self, n: Scripts) -> str:
        if isinstance(n.base, BigOp):
            lim = "undOvr" if n.limits else "subSup"
            sub = f"<m:sub>{self.node(n.sub)}</m:sub>" if n.sub is not None else "<m:sub/>"
            sup = f"<m:sup>{self.node(n.sup)}</m:sup>" if n.sup is not None else "<m:sup/>"
            hide = ('<m:subHide m:val="1"/>' if n.sub is None else "") + ('<m:supHide m:val="1"/>' if n.sup is None else "")
            return (f'<m:nary><m:naryPr><m:chr m:val="{escape(n.base.sym.text)}"/><m:limLoc m:val="{lim}"/>{hide}</m:naryPr>'
                    f"{sub}{sup}<m:e/></m:nary>")
        if n.limits:
            base = self.node(n.base)
            if n.sub is not None:
                base = f"<m:limLow><m:e>{base}</m:e><m:lim>{self.node(n.sub)}</m:lim></m:limLow>"
            if n.sup is not None:
                base = f"<m:limUpp><m:e>{base}</m:e><m:lim>{self.node(n.sup)}</m:lim></m:limUpp>"
            return base
        b = self.e(n.base)
        if n.sub is not None and n.sup is not None:
            return f"<m:sSubSup>{b}<m:sub>{self.node(n.sub)}</m:sub><m:sup>{self.node(n.sup)}</m:sup></m:sSubSup>"
        if n.sub is not None:
            return f"<m:sSub>{b}<m:sub>{self.node(n.sub)}</m:sub></m:sSub>"
        return f"<m:sSup>{b}<m:sup>{self.node(n.sup)}</m:sup></m:sSup>"

    def matrix(self, m: Matrix) -> str:
        ncol = max((len(r) for r in m.rows), default=1)
        if m.kind in ("aligned", "gathered", "pile", "lpile", "rpile", "cases") and ncol == 1:
            inner = "<m:eqArr>" + "".join(self.e(r[0]) for r in m.rows) + "</m:eqArr>"
        elif m.kind in ("aligned",):
            # alignment points are not expressible simply; join cells per line
            inner = "<m:eqArr>" + "".join("<m:e>" + "".join(self.node(c) for c in r) + "</m:e>" for r in m.rows) + "</m:eqArr>"
        else:
            rows = ""
            for r in m.rows:
                cells = list(r) + [Row()] * (ncol - len(r))
                rows += "<m:mr>" + "".join(self.e(c) for c in cells) + "</m:mr>"
            inner = f"<m:m>{rows}</m:m>"
        fences = {"pmatrix": ("(", ")"), "bmatrix": ("[", "]"), "vmatrix": ("|", "|"), "cases": ("{", "")}
        if m.kind in fences:
            o, c = fences[m.kind]
            return f'<m:d><m:dPr><m:begChr m:val="{o}"/><m:endChr m:val="{c}"/></m:dPr><m:e>{inner}</m:e></m:d>'
        return inner


def to_omml(node, display: bool = False) -> str:
    inner = _Omml().node(node)
    math = f"<m:oMath>{inner}</m:oMath>"
    if display:
        return f"<m:oMathPara>{math}</m:oMathPara>"
    return math


# =========================================================================== plain text
def to_text(node) -> str:
    """A readable linear form, e.g. for alt text and plain outputs."""
    if node is None:
        return ""
    if isinstance(node, Row):
        return "".join(to_text(i) for i in node.items)
    if isinstance(node, Sym):
        return node.text
    if isinstance(node, Text):
        return node.text
    if isinstance(node, Frac):
        return f"({to_text(node.num)})/({to_text(node.den)})"
    if isinstance(node, Binom):
        return f"C({to_text(node.n)},{to_text(node.k)})"
    if isinstance(node, Root):
        return f"√({to_text(node.body)})"
    if isinstance(node, BigOp):
        return node.sym.text
    if isinstance(node, Scripts):
        s = to_text(node.base)
        if node.sub is not None:
            s += f"_{to_text(node.sub)}"
        if node.sup is not None:
            s += f"^{to_text(node.sup)}"
        return s
    if isinstance(node, Fenced):
        return node.open + to_text(node.body) + node.close
    if isinstance(node, Accent):
        return to_text(node.body)
    if isinstance(node, Matrix):
        return "; ".join(", ".join(to_text(c) for c in r) for r in node.rows)
    return ""
