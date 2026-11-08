"""Generic credit-union product vocabulary (DECISIONS.md D-014, D-018).

Kept in one module so it can be tuned for another institution without touching the algorithm.
Families are checked in order; the first match wins (more specific families come first).
"""
from __future__ import annotations

FAMILIES = [
    ("hsa", ("health savings",)),
    ("ira", ("ira", "iras", "roth", "retirement")),
    ("home_equity", ("home equity", "heloc", "equity line")),
    ("home_improvement", ("home improvement",)),
    ("mortgage", ("mortgage", "home loan", "home loans", "conventional", "home purchase", "refinance: ")),
    ("rec_loan", ("boat", "rv", "atv", "snowmobile", "jet ski", "recreational", "camper")),
    ("auto_loan", ("auto", "vehicle", "car", "motorcycle", "model year")),
    ("student_loan", ("student",)),
    ("personal_loan", ("personal loan", "signature loan")),
    ("business_loan", ("business loan", "equipment", "commercial", "line of credit", "credit line")),
    ("credit_card", ("visa", "mastercard", "credit card", "card type")),
    ("certificate", ("certificate", "certificates", "cd", "cds")),
    ("money_market", ("money market",)),
    ("checking", ("checking",)),
    ("savings", ("savings", "saving", "holiday club", "club")),
]

# Words that never distinguish one product from another.
GENERIC_WORDS = {
    "a", "an", "and", "the", "of", "for", "to", "on", "in", "with", "your", "our", "dupaco",
    "account", "accounts", "rate", "rates", "loan", "loans", "program", "programs", "product", "products",
    "apr", "apy", "dividend", "annual", "percentage", "yield", "as", "low", "min", "earn", "open",
    "month", "months", "year", "years", "model", "term", "tier", "balance", "or", "less", "older",
    "online", "only", "option", "options", "type", "types", "personal", "deposit", "share",
}

# Flags that change which product or tier a value belongs to (part of the fact key).
IDENTITY_FLAGS = {
    "jumbo", "special", "business", "roth", "traditional", "introductory", "intro", "balance transfer",
    "purchase", "refinance", "conventional", "fha", "va", "rewards", "platinum", "heloc", "share",
    "holiday", "youth", "teen", "variable", "fixed", "student", "money market", "health savings",
}
