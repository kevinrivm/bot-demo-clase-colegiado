"""Números de México: Meta los entrega a veces como 521 + 10 dígitos y solo acepta enviar a 52 + 10 (CA-8)."""
import re


def canonico(numero: str) -> str:
    digitos = re.sub(r"\D", "", numero or "")
    if len(digitos) == 13 and digitos.startswith("521"):
        return "52" + digitos[3:]
    return digitos
