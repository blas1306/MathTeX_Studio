from __future__ import annotations

from sympy import Abs, arg, conjugate, im as sym_im, re as sym_re

from .context import ParserContext


def handle_complex_numbers(linea: str, ctx: ParserContext) -> bool:
    """Procesa comandos de números complejos."""
    latex_to_python = ctx.latex_to_python

    if linea.startswith(r"\conj(") and linea.endswith(")"):
        inner = linea[6:-1].strip()
        try:
            expr = eval(latex_to_python(inner), ctx.eval_context({"I": ctx.common_symbols.get("I")}))
            res = conjugate(expr)
            print(f"conj({inner}) = {res}")
        except Exception:
            try:
                expr = eval(latex_to_python(inner), ctx.eval_context())
                res = conjugate(expr)
                print(f"conj({inner}) = {res}")
            except Exception as e:
                print(f"Error while computing the conjugate: {e}")
        return True

    if linea.startswith(r"\Re(") and linea.endswith(")"):
        inner = linea[4:-1].strip()
        try:
            expr = eval(latex_to_python(inner), ctx.eval_context())
            print(f"Re({inner}) = {sym_re(expr)}")
        except Exception as e:
            print(f"Error while computing the real part: {e}")
        return True

    if linea.startswith(r"\Im(") and linea.endswith(")"):
        inner = linea[4:-1].strip()
        try:
            expr = eval(latex_to_python(inner), ctx.eval_context())
            print(f"Im({inner}) = {sym_im(expr)}")
        except Exception as e:
            print(f"Error while computing the imaginary part: {e}")
        return True

    if linea.startswith(r"\abs(") and linea.endswith(")"):
        inner = linea[5:-1].strip()
        try:
            expr = eval(latex_to_python(inner), ctx.eval_context())
            print(f"|{inner}| = {Abs(expr)}")
        except Exception as e:
            print(f"Error while computing the modulus: {e}")
        return True

    if linea.startswith(r"\polar(") and linea.endswith(")"):
        inner = linea[7:-1].strip()
        try:
            expr = eval(latex_to_python(inner), ctx.eval_context())
            r, theta = Abs(expr), arg(expr)
            print(f"Forma polar de {inner}: (r = {r}, theta = {theta})")
        except Exception as e:
            print(f"Error while computing the polar form: {e}")
        return True

    return False
