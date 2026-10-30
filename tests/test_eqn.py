"""Hangul equation script -> LaTeX / MathML / OMML."""
from xml.etree import ElementTree as ET

import pytest

from hwp2x.eqn import parse, to_latex, to_mathml, to_omml, to_text

LATEX = [
    ("(a+b) ^{2} =a ^{2} +2ab+b ^{2}", r"(a+b)^{2}=a^{2}+2ab+b^{2}"),
    ("{a+b} over {c}", r"\frac{a+b}{c}"),
    ("1 over 2 x", r"\frac{1}{2}x"),
    ("x = {-b +- sqrt {b^2 - 4ac}} over {2a}", r"x=\frac{-b\pm\sqrt{b^{2}-4ac}}{2a}"),
    ("sum from {k=1} to n k^2", r"\sum_{k=1}^{n}k^{2}"),
    ("int from 0 to inf e^{-x^2} dx", r"\int_{0}^{\infty}e^{-x^{2}}dx"),
    ("lim from {x -> 0} {sin x} over x = 1", r"\lim_{x\to0}\frac{\sin x}{x}=1"),
    ("root 3 of {x+1}", r"\sqrt[3]{x+1}"),
    ("left | x right |", r"\left| x \right|"),
    ("pmatrix{1 & 0 # 0 & 1}", r"\begin{pmatrix} 1 & 0 \\ 0 & 1 \end{pmatrix}"),
    ("f(x) = cases{x & (x >= 0) # -x & (x<0)}",
     r"f(x)=\begin{cases} x & (x\ge0) \\ -x & (x<0) \end{cases}"),
    ("bar {AB} + vec a", r"\overline{AB}+\overrightarrow{a}"),
    ("ALPHA alpha PI pi", r"\mathrm{A}\alpha\Pi\pi"),
    ("E = mc^2", r"E=mc^{2}"),
    ("n choose k", r"\binom{n}{k}"),
    ("a &= b # &= c", r"\begin{aligned} a & =b \\ & =c \end{aligned}"),
    ("therefore A RARROW B", r"\therefore A\Rightarrow B"),
    ('"속도" = {"거리"} over {"시간"}', r"\text{속도}=\frac{\text{거리}}{\text{시간}}"),
]


@pytest.mark.parametrize("script,expected", LATEX)
def test_latex(script, expected):
    assert to_latex(parse(script))[0] == expected


def test_hangul_profiles():
    t = parse("ㄱ + ㄴ = 가 + 나다")
    tex, uses = to_latex(t, "tex")
    assert tex == r"\giug+\niun=\text{가}+\text{나다}" and uses
    htex, uses = to_latex(t, "htex")
    assert htex == r"ㄱ+ㄴ=가+\text{나다}" and not uses
    md, _ = to_latex(t, "md")
    assert md == r"\text{ㄱ}+\text{ㄴ}=\text{가}+\text{나다}"


def test_rieul_avoids_kotex_clash():
    assert to_latex(parse("ㄹ"), "tex")[0] == r"\liul"


@pytest.mark.parametrize("script", [s for s, _ in LATEX] + [
    "{", "}", "left ( x", "x^", "#&#", "a over", "sqrt", "matrix", "\"unterminated", "", "   ",
])
def test_always_produces_wellformed_output(script):
    t = parse(script)
    to_latex(t)
    ET.fromstring(to_mathml(t, True))
    ET.fromstring('<r xmlns:m="m" xmlns:w="w">' + to_omml(t, True) + "</r>")
    to_text(t)


def test_mathml_structure():
    m = to_mathml(parse("{a} over {b}"))
    assert "<mfrac><mi>a</mi><mi>b</mi></mfrac>" in m


def test_omml_nary_and_fraction():
    o = to_omml(parse("sum from {i=1} to n {1} over i"))
    assert '<m:chr m:val="∑"/>' in o and '<m:limLoc m:val="undOvr"/>' in o and "<m:f>" in o
