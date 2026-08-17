"""Lightweight LaTeX → readable-Unicode cleanup for paper text.

arXiv abstracts (and their AI translations) embed math in ``$...$`` /
``$$...$$`` delimiters. The papers library has no JS math renderer and is
Chinese-first, so instead of shipping a full TeX renderer we rewrite the
common constructs into readable Unicode text at ingestion time (and via the
``--clean-latex`` backfill for already-stored rows).

This is deliberately an *approximate* cleanup — the goal is a readable
Chinese abstract, not a faithful mathematical rendering. Unmapped commands
have their backslash stripped (e.g. ``backslash-whatever`` → ``whatever``),
which reads better than raw LaTeX and is harmless.
"""

import re
from typing import Dict, Optional

__all__ = ["latex_to_unicode"]

# ── Unicode super/subscripts for _x / x^2 → x₁ / x² ──────────────────────
_SUPERSCRIPTS: Dict[str, str] = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
    "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
    "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽", ")": "⁾",
    "n": "ⁿ", "i": "ⁱ", "T": "ᵀ",
    "a": "ᵃ", "b": "ᵇ", "c": "ᶜ", "d": "ᵈ", "e": "ᵉ",
    "f": "ᶠ", "g": "ᵍ", "h": "ʰ", "j": "ʲ", "k": "ᵏ",
    "l": "ˡ", "m": "ᵐ", "o": "ᵒ", "p": "ᵖ", "r": "ʳ",
    "s": "ˢ", "t": "ᵗ", "u": "ᵘ", "v": "ᵛ", "w": "ʷ",
    "x": "ˣ", "y": "ʸ",
}

_SUBSCRIPTS: Dict[str, str] = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
    "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
    "+": "₊", "-": "₋", "=": "₌", "(": "₍", ")": "₎",
    "a": "ₐ", "e": "ₑ", "h": "ₕ", "i": "ᵢ", "j": "ⱼ",
    "k": "ₖ", "l": "ₗ", "m": "ₘ", "n": "ₙ", "o": "ₒ",
    "p": "ₚ", "r": "ᵣ", "s": "ₛ", "t": "ₜ", "u": "ᵤ",
    "v": "ᵥ", "x": "ₓ",
    "β": "ᵦ", "γ": "ᵧ", "ρ": "ᵨ",
    "φ": "ᵩ", "χ": "ᵪ",
}


def _to_super(s: str) -> str:
    return "".join(_SUPERSCRIPTS.get(ch, ch) for ch in s)


def _to_sub(s: str) -> str:
    return "".join(_SUBSCRIPTS.get(ch, ch) for ch in s)


# ── Fixed commands → Unicode (longest first so prefixes don't shadow) ─────
_COMMAND_MAP: Dict[str, str] = {
    # accents handled separately; these are the no-brace wrapper forms
    r"\boldsymbol": "",
    r"\operatorname": "",
    r"\mathbb": "",
    r"\mathcal": "",
    r"\mathbf": "",
    r"\mathrm": "",
    r"\mathsf": "",
    r"\mathit": "",
    r"\argmin": "arg min",
    r"\argmax": "arg max",
    r"\arg": "arg",
    r"\limsup": "lim sup",
    r"\liminf": "lim inf",
    r"\lim": "lim",
    r"\log": "log",
    r"\ln": "ln",
    r"\exp": "exp",
    r"\max": "max",
    r"\min": "min",
    r"\sup": "sup",
    r"\inf": "inf",
    r"\det": "det",
    r"\Pr": "Pr",
    r"\sin": "sin",
    r"\cos": "cos",
    r"\tan": "tan",
    r"\qquad": "  ",
    r"\quad": " ",
    r"\left": "",
    r"\right": "",
    r"\nolimits": "",
    r"\limits": "",
    r"\displaystyle": "",
    r"\textstyle": "",
    # bars / delimiters
    r"\|": "‖",           # ‖
    r"\Vert": "‖",
    r"\lVert": "‖",
    r"\rVert": "‖",
    r"\lvert": "|",
    r"\rvert": "|",
    r"\mid": "|",
    r"\vert": "|",
    r"\langle": "⟨",
    r"\rangle": "⟩",
    r"\lceil": "⌈",
    r"\rceil": "⌉",
    r"\lfloor": "⌊",
    r"\rfloor": "⌋",
    # relations (specific before generic prefixes)
    r"\subseteq": "⊆",
    r"\supseteq": "⊇",
    r"\nsubseteq": "⊈",
    r"\nsupseteq": "⊉",
    r"\subset": "⊂",
    r"\supset": "⊃",
    r"\leq": "≤",
    r"\leqslant": "≤",
    r"\geq": "≥",
    r"\geqslant": "≥",
    r"\le": "≤",
    r"\ge": "≥",
    r"\neq": "≠",
    r"\ne": "≠",
    r"\approx": "≈",
    r"\simeq": "≃",
    r"\equiv": "≡",
    r"\propto": "∝",
    r"\sim": "∼",
    r"\prec": "≺",
    r"\succ": "≻",
    r"\ll": "≪",
    r"\gg": "≫",
    # logic
    r"\implies": "⇒",
    r"\iff": "⇔",
    r"\Leftrightarrow": "⇔",
    r"\Rightarrow": "⇒",
    r"\rightarrow": "→",
    r"\to": "→",
    r"\Leftarrow": "⇐",
    r"\leftarrow": "←",
    r"\mapsto": "↦",
    r"\forall": "∀",
    r"\exists": "∃",
    r"\nexists": "∄",
    r"\land": "∧",
    r"\lor": "∨",
    r"\lnot": "¬",
    # set / membership (specific before generic)
    r"\notin": "∉",
    r"\not\in": "∉",
    r"\in": "∈",
    r"\cup": "∪",
    r"\cap": "∩",
    r"\bigcup": "⋃",
    r"\bigcap": "⋂",
    r"\setminus": "∖",
    r"\emptyset": "∅",
    r"\varnothing": "∅",
    # arithmetic
    r"\infty": "∞",
    r"\pm": "±",
    r"\mp": "∓",
    r"\times": "×",
    r"\div": "÷",
    r"\cdot": "·",
    r"\ast": "∗",
    r"\star": "⋆",
    r"\circ": "∘",
    r"\partial": "∂",
    r"\nabla": "∇",
    r"\ldots": "…",
    r"\dots": "…",
    r"\cdots": "⋯",
    r"\vdots": "⋮",
    r"\ddots": "⋱",
    r"\prime": "′",
    # operators
    r"\sum": "Σ",
    r"\prod": "∏",
    r"\int": "∫",
    r"\oint": "∮",
    # Greek lowercase (specific before generic)
    r"\varepsilon": "ε",
    r"\epsilon": "ε",
    r"\vartheta": "ϑ",
    r"\theta": "θ",
    r"\varpi": "ϖ",
    r"\pi": "π",
    r"\varrho": "ϱ",
    r"\rho": "ρ",
    r"\varsigma": "ς",
    r"\sigma": "σ",
    r"\varphi": "φ",
    r"\phi": "φ",
    r"\alpha": "α",
    r"\beta": "β",
    r"\gamma": "γ",
    r"\delta": "δ",
    r"\zeta": "ζ",
    r"\eta": "η",
    r"\iota": "ι",
    r"\kappa": "κ",
    r"\lambda": "λ",
    r"\mu": "μ",
    r"\nu": "ν",
    r"\xi": "ξ",
    r"\tau": "τ",
    r"\upsilon": "υ",
    r"\chi": "χ",
    r"\psi": "ψ",
    r"\omega": "ω",
    # Greek uppercase
    r"\Gamma": "Γ",
    r"\Delta": "Δ",
    r"\Theta": "Θ",
    r"\Lambda": "Λ",
    r"\Xi": "Ξ",
    r"\Pi": "Π",
    r"\Sigma": "Σ",
    r"\Upsilon": "Υ",
    r"\Phi": "Φ",
    r"\Psi": "Ψ",
    r"\Omega": "Ω",
}

# Combining marks appended to the last char of \overline{…} / \hat{…} etc.
_ACCENTS: Dict[str, str] = {
    r"\overline": "̅",   # combining overline
    r"\bar": "̄",        # combining macron
    r"\hat": "̂",        # combining circumflex
    r"\tilde": "̃",      # combining tilde
    r"\vec": "⃗",        # combining right-arrow above
    r"\dot": "̇",        # combining dot above
    r"\ddot": "̈",       # combining diaeresis
}

# Format wrappers whose braces hold the real content: \mathbb{R} → R
_FORMAT_RE = re.compile(
    r"\\(?:mathbb|mathcal|mathbf|mathrm|mathsf|mathit|boldsymbol|bm|"
    r"operatorname|text|textrm|texttt|mbox|rm|bf|it)\s*\{([^{}]*)\}"
)


def _replace_braced_commands(s: str) -> str:
    s = _FORMAT_RE.sub(r"\1", s)
    for cmd, mark in _ACCENTS.items():
        s = re.sub(
            re.escape(cmd) + r"\s*\{([^{}]*)\}",
            lambda m, m2=mark: m.group(1) + m2,
            s,
        )
    # \frac{a}{b} → a/b ; \binom{a}{b} → C(a,b)
    s = re.sub(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"\1/\2", s)
    s = re.sub(r"\\binom\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"C(\1,\2)", s)
    # \sqrt[n]{x} → x^(1/n) ; \sqrt{x} → √x
    s = re.sub(
        r"\\sqrt\s*\[([^{}]*)\]\s*\{([^{}]*)\}",
        lambda m: f"{m.group(2)}^(1/{m.group(1)})",
        s,
    )
    s = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"√\1", s)
    return s


def latex_to_unicode(text: Optional[str]) -> Optional[str]:
    """Rewrite LaTeX math in *text* into readable Unicode.

    Returns ``None`` for ``None`` input, otherwise the cleaned string (which
    may equal the input when it contains no LaTeX). Idempotent: applying it
    twice never changes the result.
    """
    if not text:
        return text
    s = text
    # 1. math delimiters
    s = s.replace("$$", "")
    s = s.replace("$", "")
    # 2. braced commands (frac / sqrt / accents / format wrappers)
    s = _replace_braced_commands(s)
    # 3. fixed commands
    for key, val in _COMMAND_MAP.items():
        s = s.replace(key, val)
    # 4. spacing escapes
    s = s.replace(r"\,", " ")
    s = s.replace(r"\;", " ")
    s = s.replace(r"\!", "")
    s = s.replace(r"\ ", " ")
    # 5. line break \\ and alignment separators
    s = s.replace(r"\\", " ")
    s = s.replace("&", " ")
    # 6. super/subscripts — braced first, then single chars
    s = re.sub(r"_\{([^{}]*)\}", lambda m: _to_sub(m.group(1)), s)
    s = re.sub(r"\^\{([^{}]*)\}", lambda m: _to_super(m.group(1)), s)
    s = re.sub(r"_([A-Za-z0-9])", lambda m: _to_sub(m.group(1)), s)
    s = re.sub(r"\^([A-Za-z0-9])", lambda m: _to_super(m.group(1)), s)
    # 7. strip leftover backslashes / grouping braces / latex non-break space
    s = re.sub(r"\\([A-Za-z]+)", r"\1", s)  # unknown command: \foo → foo
    s = re.sub(r"[{}]", "", s)
    s = re.sub(r"\\", "", s)  # any remaining lone backslash (e.g. before digits)
    s = s.replace("~", " ")
    # 8. collapse runs of whitespace introduced by the rewrites
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()
