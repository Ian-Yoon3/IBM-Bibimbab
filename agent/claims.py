"""Check comparison claims in AI-written sentences against the table values.

The number check (agent/render.check_explanation) only asks whether a number
appears in the view.  It does not see a wrong direction, for example "TRANSFER
has a higher chance than HYBRID" when the table says the opposite.  This module
reads each sentence, finds the comparison words in it (higher, fewer, the most,
cheaper, "3 fewer", "save $416", "ranging from"), works out which column and
which options the sentence talks about, and compares the table values.

Rule for anything it cannot read: a sentence that contains a comparison word
which cannot be tied to a column and to options on both sides is treated as
NOT confirmed.  The caller then leaves the text out.  A correct sentence can be
left out this way; a comparison is never passed on the benefit of the doubt.

Known limits (see docs/ui-contract.md):
- Only the listed comparison words and two general patterns ("<word>er than",
  "the <word>est") are recognised.  A comparison made with other words
  ("beats" is listed, "has an edge over" is not) is not seen.
- A number given for the wrong option or the wrong column is not checked here
  unless it is part of a comparison ("increase on-time orders to 9").
"""
from __future__ import annotations

import re

# ── vocabulary ───────────────────────────────────────────────────────────────

_MONEY = r"\$\d{1,3}(?:,\d{3})+(?:\.\d+)?|\$\d+(?:\.\d+)?"
_MONTH = (r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?")

# Neutral wordings that contain a comparison word but compare nothing.
_IDIOMS = [
    r"at or (?:below|above|under|over)",
    r"or (?:more|fewer|less|higher|lower)\b",
    r"no (?:later|earlier) than",
    r"at the (?:latest|earliest)",
    r"the (?:latest|earliest)",
    r"(?:worst|best)[- ]case",
    r"at (?:best|worst)",
    r"more or less",
    r"most of\b",
    r"at the same time",
    r"(?:other|rather) than",
    r"(?:the )?same (?:column|columns|table|row|date|day|time|way|reason|option|"
    r"supplier|order|question|situation)\b",
    _MONTH + r" \d{1,2}(?:st|nd|rd|th)?\b",
    r"\d{4}-\d{2}-\d{2}",
    r"priority[- ]1",
    r"\d+(?:st|nd|rd|th)\b",
]

_BUDGET_WITHIN = [
    r"(?:with)?in (?:the |a |our |your |their )?(?:(?P<a>" + _MONEY + r") )?budget"
    r"(?: of (?P<b>" + _MONEY + r"))?",
    r"within (?P<c>" + _MONEY + r")",
    r"(?:under|on) budget",
]
_BUDGET = (r"(?:the |a |our |your |their )?(?:(?P<a>" + _MONEY + r") )?budget"
           r"(?: limit)?(?: of (?P<b>" + _MONEY + r"))?")
_COMPARE = (r"compared (?:to|with)|in comparison (?:to|with)|relative to|versus|"
            r"vs\.?|unlike|in contrast to|as opposed to")
_OTHERS = (r"(?:all |any |every |each )?(?:of )?(?:the )?other "
           r"(?:options?|choices?|rows?|alternatives?|ones?)|"
           r"(?:all |any of )?the others|all others|the rest|the alternatives|"
           r"all (?:the )?options|every option")
_STAR_STRONG = (r"this option|that option|the recommended option|the recommendation|"
                r"the engine'?s (?:choice|pick|recommendation)|this choice|"
                r"the starred option")
_STAR_WEAK = r"it|its|this"

# Comparison wordings that are recognised but can never be confirmed here.
_UNVERIFIABLE = [
    r"no other\b", r"none of the other\w*",
    r"the only (?:option|one|choice|way|row|alternative)",
    r"twice", r"doubl\w*", r"half", r"halv\w*", r"tripl\w*",
    r"\d+(?:\.\d+)? ?(?:x|times)\b",
    r"outperform\w*", r"beats?", r"beating", r"superior", r"inferior",
    r"safer", r"safest", r"riskier", r"riskiest", r"dominat\w*",
    r"second[- ](?:best|lowest|highest|most|cheapest|fewest|worst)",
    r"runner[- ]up", r"ranks?", r"ranked", r"outrank\w*",
    r"as (?:many|much|few|little|low|high|good|bad|cheap|expensive|well)\b",
    r"tied?", r"ties",
]

# (pattern, kind, direction, valence?, implied metric, needs explicit reference)
#   kind: comp / super / equal / range / save
#   direction: +1 greater, -1 smaller.  valence=True: +1 means "better".
_CUES = [
    (r"more expensive|costlier|pricier|costs? more", "comp", +1, False, "cost", False),
    (r"less expensive|cheaper|costs? less", "comp", -1, False, "cost", False),
    (r"most expensive|costliest|priciest", "super", +1, False, "cost", False),
    (r"least expensive|cheapest", "super", -1, False, "cost", False),
    (r"rang(?:e|es|ing|ed) from", "range", 0, False, None, False),
    (r"the same|same|equal(?:s|ly)?|identical", "equal", 0, False, None, False),
    (r"sav(?:e|es|ed|ing)s?", "save", -1, False, "cost", False),
    (r"above|exceed\w*|over(?= (?:the |a |our |your )?(?:\$[\d,.]+ )?budget)",
     "comp", +1, False, None, True),
    (r"below|under(?= (?:the |a |our |your )?(?:\$[\d,.]+ )?budget)",
     "comp", -1, False, None, True),
    (r"higher|greater|larger|bigger|more|longer", "comp", +1, False, None, False),
    (r"lower|smaller|fewer|less|shorter", "comp", -1, False, None, False),
    (r"highest|greatest|largest|biggest|most|longest|maximum", "super", +1, False, None, False),
    (r"lowest|smallest|fewest|least|shortest|minimum", "super", -1, False, None, False),
    (r"better", "comp", +1, True, None, False),
    (r"worse", "comp", -1, True, None, False),
    (r"best", "super", +1, True, None, False),
    (r"worst", "super", -1, True, None, False),
    (r"improv\w*", "comp", +1, True, None, False),
    (r"worsen\w*", "comp", -1, True, None, False),
    (r"increas\w*|rais(?:e|es|ed|ing)|ris(?:e|es|ing)|rose|go(?:es)? up|grow\w*",
     "comp", +1, False, None, False),
    (r"reduc\w*|decreas\w*|lower(?:s|ed|ing)|cut(?:s|ting)?|drop(?:s|ped|ping)?|"
     r"fall(?:s|ing)?|fell|go(?:es)? down|shrink\w*", "comp", -1, False, None, False),
]

_FILLER = {
    "the", "a", "an", "of", "number", "numbers", "overall", "even", "much",
    "slightly", "significantly", "far", "somewhat", "substantially",
    "considerably", "value", "values", "figure", "amount", "level",
    "option", "options", "choice", "scenario", "row",
}
_VERB = {
    "has", "have", "having", "had", "is", "are", "was", "were", "be", "being",
    "been", "would", "will", "can", "could", "does", "do", "did", "result",
    "results", "resulting", "keep", "keeps", "cost", "costs", "give", "gives",
    "offer", "offers", "achieve", "achieves", "remain", "remains", "stay",
    "stays", "come", "comes", "leave", "leaves",
}
_FUNC = {
    "for", "with", "in", "at", "among", "amongst", "across", "when", "if",
    "under", "on", "because", "while", "but", "as", "so", "whereas",
    "although", "though", "then", "also", "still", "only", "just", "however",
    "since", "per", "into", "out", "between", "within", "according", "shown",
    "showing", "shows", "show", "indicating", "indicates", "meaning", "means",
    "making", "due", "given", "where", "all", "like", "such", "including",
}
_NEG = r"not|no|never|neither|nor|without|cannot|\w+n['’]t"
_EST_OK = {"rest", "request", "test", "interest", "west", "guest", "forest",
           "contest", "quest", "suggest", "manifest", "harvest", "invest",
           "nearest"}
_ER_OK = {"other", "rather"}


def _compile(p):
    return re.compile(r"(?:" + p + r")(?![\w])", re.I)


_FIXED = (
    [("IDIOM", _compile(p), None) for p in _IDIOMS]
    + [("BUDGETQ", _compile(p), None) for p in _BUDGET_WITHIN]
    + [("BUDGET", _compile(_BUDGET), None)]
    + [("COMPARE", _compile(_COMPARE), None)]
    + [("UNVER", _compile(p), None) for p in _UNVERIFIABLE[:3]]
    + [("OTHERS", _compile(_OTHERS), None)]
    + [("STAR", _compile(_STAR_STRONG), None)]
    + [("UNVER", _compile(p), None) for p in _UNVERIFIABLE[3:]]
    + [("CUE", _compile(p), {"kind": k, "dir": d, "val": v, "metric": m, "explicit": e})
       for p, k, d, v, m, e in _CUES]
    + [("THAN", _compile(r"than"), None),
       ("REL", _compile(r"which|that|who"), None),
       ("NEG", _compile(_NEG), None),
       ("QUAL", _compile(r"at least|at most"), None),
       ("FROM", _compile(r"from"), None),
       ("TO", _compile(r"to"), None),
       ("BY", _compile(r"by"), None),
       ("AND", _compile(r"and"), None),
       ("OR", _compile(r"or"), None),
       ("WEAK", _compile(_STAR_WEAK), None)]
)
_NUM_RE = re.compile(
    r"(?P<money>\$)?(?P<n>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?P<pct>%)?"
    r"(?:(?: out)? of \d+)?(?![\w])")
_WORD_RE = re.compile(r"[A-Za-z_][\w'’-]*")


def _money_value(s):
    return float(s.replace("$", "").replace(",", "")) if s else None


def _decimals(s: str) -> int:
    return len(s.split(".")[1]) if "." in s else 0


# ── tokens ───────────────────────────────────────────────────────────────────

def _tokenize(sent: str, table: dict) -> list:
    aliases = sorted(table["aliases"], key=lambda a: -len(a[0]))
    metrics = [(re.compile(r"(?:" + p + r")(?![\w])", re.I), keys)
               for p, keys in table["metrics"]]
    toks, i, n = [], 0, len(sent)
    while i < n:
        ch = sent[i]
        if not (ch.isalnum() or ch in "$_"):
            if ch == ",":
                toks.append({"t": "COMMA", "raw": ","})
            i += 1
            continue
        if i and (sent[i - 1].isalnum() or sent[i - 1] == "_"):
            i += 1          # inside a word (should not happen); move on
            continue
        hit = None
        for lit, code in aliases:
            if sent.startswith(lit, i):
                j = i + len(lit)
                if j < n and (sent[j].isalnum() or sent[j] == "_"):
                    continue
                m = re.match(r"['’]s", sent[j:])
                hit = ({"t": "CODE", "code": code, "raw": lit}, j + (m.end() if m else 0))
                break
        if hit is None:
            for rx, keys in metrics:
                m = rx.match(sent, i)
                if m:
                    hit = ({"t": "METRIC", "keys": list(keys), "raw": m.group()}, m.end())
                    break
        if hit is None:
            for typ, rx, payload in _FIXED:
                m = rx.match(sent, i)
                if not m:
                    continue
                tok = {"t": typ, "raw": m.group()}
                if payload:
                    tok.update(payload)
                if typ in ("BUDGET", "BUDGETQ"):
                    gd = m.groupdict()
                    tok["amount"] = _money_value(gd.get("a") or gd.get("b") or gd.get("c"))
                hit = (tok, m.end())
                break
        if hit is None:
            m = _NUM_RE.match(sent, i)
            if m:
                hit = ({"t": "NUM", "raw": m.group(),
                        "value": float(m.group("n").replace(",", "")),
                        "money": bool(m.group("money")),
                        "dec": _decimals(m.group("n"))}, m.end())
        if hit is None:
            m = _WORD_RE.match(sent, i)
            if m:
                w = m.group().lower()
                typ = ("FILLER" if w in _FILLER else "VERB" if w in _VERB
                       else "FUNC" if w in _FUNC else "WORD")
                hit = ({"t": typ, "raw": m.group()}, m.end())
            else:
                i += 1
                continue
        tok, i = hit
        # the same option written twice in a row: "Move stock ... (HYBRID)"
        if tok["t"] == "CODE" and toks and toks[-1]["t"] == "CODE" \
                and toks[-1]["code"] == tok["code"]:
            continue
        toks.append(tok)
    # general patterns: "<word>er than" and "the <word>est"
    for k, t in enumerate(toks):
        if t["t"] != "WORD":
            continue
        w = t["raw"].lower()
        nxt = toks[k + 1] if k + 1 < len(toks) else None
        prv = toks[k - 1] if k else None
        if w.endswith("er") and w not in _ER_OK and nxt and nxt["t"] == "THAN":
            t["t"] = "UNVER"
        elif (w.endswith("est") and len(w) > 4 and w not in _EST_OK
              and prv and prv["raw"].lower() == "the"):
            t["t"] = "UNVER"
    return toks


def _sentences(text: str) -> list:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [p.strip() for p in parts if p and p.strip()]


# ── reading one sentence ─────────────────────────────────────────────────────

class _Unverifiable(Exception):
    pass


class _Wrong(Exception):
    pass


def _typ(toks, i):
    return toks[i]["t"] if 0 <= i < len(toks) else "END"


def _code_group(toks, j):
    """Codes joined by commas/and/or starting at j.  A later code that is
    followed by a verb starts a new statement and is not part of the group."""
    idxs = [j]
    k = j + 1
    while True:
        m = k
        seen_join = False
        while _typ(toks, m) in ("COMMA", "AND", "OR", "FILLER", "NUM"):
            seen_join = seen_join or _typ(toks, m) in ("COMMA", "AND", "OR")
            m += 1
        if not seen_join or _typ(toks, m) != "CODE":
            break
        after = m + 1
        while _typ(toks, after) == "FILLER":
            after += 1
        if _typ(toks, after) == "VERB":
            break
        idxs.append(m)
        k = m + 1
    return idxs


def _group_back(toks, j):
    """Code group that ends at j (walk left over commas/and/or)."""
    idxs = [j]
    k = j - 1
    while True:
        m = k
        seen_join = False
        while _typ(toks, m) in ("COMMA", "AND", "OR", "FILLER", "NUM"):
            seen_join = seen_join or _typ(toks, m) in ("COMMA", "AND", "OR")
            m -= 1
        if not seen_join or _typ(toks, m) != "CODE":
            break
        idxs.insert(0, m)
        k = m - 1
    return idxs


def _parse_ref(toks, j, cue_keys=None):
    """What stands after 'than' / 'compared to' / a preposition cue."""
    skipped = 0
    while _typ(toks, j) in ("FILLER", "FUNC", "METRIC", "REL") and skipped < 5:
        if toks[j]["t"] == "METRIC" and cue_keys is not None \
                and toks[j]["keys"] != cue_keys:
            return None, []
        if toks[j]["t"] == "FUNC" and toks[j]["raw"].lower() not in (
                "for", "with", "in", "under", "all"):
            return None, []
        j += 1
        skipped += 1
    t = _typ(toks, j)
    if t == "CODE":
        g = _code_group(toks, j)
        return {"kind": "codes", "codes": [toks[k]["code"] for k in g]}, g
    if t == "NUM":
        return {"kind": "num", "tok": toks[j]}, []
    if t == "BUDGET":
        return {"kind": "budget", "amount": toks[j].get("amount")}, []
    if t == "OTHERS":
        used = []
        k = j + 1
        if _typ(toks, k) == "COMMA":
            k += 1
        if _typ(toks, k) == "FUNC" and toks[k]["raw"].lower() in ("like", "such", "including"):
            k += 1
            while _typ(toks, k) in ("FUNC", "FILLER"):
                k += 1
            if _typ(toks, k) == "CODE":      # "other options like WAIT"
                used = _code_group(toks, k)
        return {"kind": "others"}, used
    if t == "STAR":
        return {"kind": "star"}, []
    return None, []


def _close(value, tok, loose=False) -> bool:
    unit = 10 ** (-tok["dec"])
    tol = (unit if (loose and tok["dec"]) else unit / 2) + 1e-9
    return abs(value - tok["value"]) <= tol


class _Sentence:
    def __init__(self, sent, table, star, budget):
        self.table, self.star, self.budget = table, star, budget
        self.rows = table["rows"]
        self.toks = _tokenize(sent, table)
        self.consumed = set()
        self.than_ref = {}
        self.compare_refs = []          # (index, ref, code idxs)
        self.cue_keys = {}              # cue index -> metric keys
        self.last = None                # (subject, ref codes) of the last comparison

    # values ------------------------------------------------------------------
    def val(self, code, key):
        v = self.rows.get(code, {}).get(key)
        if v is None or isinstance(v, (list, tuple, dict, str)):
            raise _Unverifiable(f"no single value for {key!r} of {code!r}")
        return v

    def budget_value(self, amount=None):
        """The budget of the request.  A budget that only the text mentions is
        not a known limit; a different amount than the request's is wrong."""
        if self.budget is None:
            raise _Unverifiable("the request has no budget")
        if amount is not None and abs(amount - self.budget) > 1e-9:
            raise _Wrong(f"the budget is {self.budget:g}, not {amount:g}")
        return self.budget

    # metric ------------------------------------------------------------------
    def _chain_fwd(self, j):
        keys, end = [self.toks[j]["keys"]], j
        k = j + 1
        while _typ(self.toks, k) in ("AND", "OR", "COMMA"):
            m = k + 1
            while _typ(self.toks, m) == "FILLER":
                m += 1
            if _typ(self.toks, m) != "METRIC" or _typ(self.toks, m + 1) == "VERB":
                break
            keys.append(self.toks[m]["keys"])
            end, k = m, m + 1
        return keys, end

    def _chain_back(self, j):
        keys = [self.toks[j]["keys"]]
        k = j - 1
        while True:
            m = k
            while _typ(self.toks, m) == "FILLER":
                m -= 1
            if _typ(self.toks, m) not in ("AND", "OR", "COMMA"):
                break
            m -= 1
            while _typ(self.toks, m) == "FILLER":
                m -= 1
            if _typ(self.toks, m) != "METRIC":
                break
            keys.insert(0, self.toks[m]["keys"])
            k = m - 1
        return keys

    def metric_for(self, i):
        """-> (list of key lists, index of the last metric token or None)."""
        toks, cue = self.toks, self.toks[i]
        j = i + 1
        while _typ(toks, j) == "FILLER":
            j += 1
        if _typ(toks, j) == "FUNC" and toks[j]["raw"].lower() == "in":
            m = j + 1                         # "an increase in extra cost"
            while _typ(toks, m) == "FILLER":
                m += 1
            if _typ(toks, m) == "METRIC":
                j = m
        t = _typ(toks, j)
        if t == "METRIC":
            return self._chain_fwd(j)
        if cue.get("metric") == "cost":
            return [[self.table["cost_key"]]], None
        if t == "WORD":
            raise _Unverifiable(f"{cue['raw']!r} is followed by {toks[j]['raw']!r}, "
                                "which is not a column")
        if t == "THAN":                       # "more than 5 on-time orders"
            m = j + 1
            if _typ(toks, m) == "NUM":
                m += 1
                while _typ(toks, m) == "FILLER":
                    m += 1
                if _typ(toks, m) == "METRIC":
                    return [toks[m]["keys"]], None
        # look left for the column the sentence is about
        k = i - 1
        while k >= 0:
            tk = toks[k]["t"]
            if tk == "METRIC":
                return self._chain_back(k), None
            if tk == "CUE" and k in self.cue_keys:
                return self.cue_keys[k], None
            if tk in ("CUE", "UNVER"):
                break
            k -= 1
        return None, None

    # subject -----------------------------------------------------------------
    def subject_for(self, i, allow_after=False):
        toks = self.toks
        # "WAIT and TRANSFER, which have fewer ..."
        k = i - 1
        while k >= 0 and toks[k]["t"] not in ("CODE", "STAR", "REL"):
            k -= 1
        if k >= 0 and toks[k]["t"] == "REL":
            m = k - 1
            while _typ(toks, m) in ("COMMA", "FILLER"):
                m -= 1
            if _typ(toks, m) == "CODE":
                g = _group_back(toks, m)
                return [toks[x]["code"] for x in g], set(g)
        weak = False
        k = i - 1
        while k >= 0:
            t = toks[k]
            if t["t"] == "CODE" and k not in self.consumed:
                g = _group_back(toks, k)
                g = [x for x in g if x not in self.consumed]
                return [toks[x]["code"] for x in g], set(g)
            if t["t"] == "STAR" and self.star:
                return [self.star], set()
            if t["t"] == "WEAK":
                weak = True
            k -= 1
        if weak and self.star:
            return [self.star], set()
        if allow_after:
            k = i + 1
            while k < len(toks) and toks[k]["t"] not in ("CUE", "UNVER", "THAN"):
                if toks[k]["t"] == "CODE" and k not in self.consumed:
                    g = [x for x in _code_group(toks, k) if x not in self.consumed]
                    return [toks[x]["code"] for x in g], set(g)
                if toks[k]["t"] == "STAR" and self.star:
                    return [self.star], set()
                k += 1
        return None, set()

    def negated(self, i):
        for k in range(i - 1, max(i - 4, -1), -1):
            t = self.toks[k]["t"]
            if t == "NEG":
                return True
            if t in ("CODE", "CUE", "METRIC", "NUM"):
                return False
        return False

    # preparation -------------------------------------------------------------
    def prepare(self):
        toks = self.toks
        for i, t in enumerate(toks):
            if t["t"] == "THAN":
                ref, used = _parse_ref(toks, i + 1)
                self.than_ref[i] = ref
                self.consumed.update(used)
            elif t["t"] == "COMPARE":
                ref, used = _parse_ref(toks, i + 1)
                if ref:
                    self.compare_refs.append((i, ref, set(used)))
                    self.consumed.update(used)

    # checks ------------------------------------------------------------------
    def check(self):
        toks = self.toks
        types = [t["t"] for t in toks]
        if not any(t in ("CUE", "UNVER", "BUDGETQ", "THAN") for t in types):
            if "OTHERS" in types and re.search(r"\b(?:any|no) other\b",
                                               " ".join(t["raw"] for t in toks), re.I):
                raise _Unverifiable("statement about every other option")
            return
        self.prepare()
        seen_cue = False
        for t in toks:
            if t["t"] == "CUE" and t["kind"] in ("comp", "save"):
                seen_cue = True
            elif t["t"] == "THAN":
                if not seen_cue:
                    raise _Unverifiable("'than' after a comparison word that is not known")
                seen_cue = False
        for i, t in enumerate(toks):
            if t["t"] == "UNVER":
                raise _Unverifiable(f"{t['raw']!r} cannot be checked against the table")
            if t["t"] == "BUDGETQ":
                self.check_within_budget(i)
            elif t["t"] == "CUE":
                {"comp": self.check_comp, "save": self.check_comp,
                 "super": self.check_super, "equal": self.check_equal,
                 "range": self.check_range}[t["kind"]](i)

    def _keys(self, i, default_cost=False):
        chains, end = self.metric_for(i)
        if chains is None:
            if default_cost:
                chains = [[self.table["cost_key"]]]
            else:
                raise _Unverifiable(f"no column found for {self.toks[i]['raw']!r}")
        self.cue_keys[i] = chains
        return [k for ks in chains for k in ks], end

    def _direction(self, cue, key):
        d = cue["dir"]
        if cue["val"]:
            d *= self.table["better"].get(key, 0)
            if d == 0:
                raise _Unverifiable(f"no better/worse direction for {key!r}")
        return d

    def _resolve_ref(self, ref, subject):
        """-> list of (label, value getter per key)."""
        if ref["kind"] == "codes":
            codes = ref["codes"]
        elif ref["kind"] == "others":
            codes = [c for c in self.rows if c not in subject]
        elif ref["kind"] == "star":
            if not self.star:
                raise _Unverifiable("no recommended option to compare with")
            codes = [self.star]
        else:
            return None
        codes = [c for c in codes if c not in subject]
        if not codes:
            raise _Unverifiable("nothing to compare with")
        return codes

    def check_comp(self, i):
        toks, cue = self.toks, self.toks[i]
        neg = self.negated(i)
        # magnitude written before the word: "3 fewer", "$416 less"
        mag = None
        if cue["kind"] == "comp" and not cue["explicit"] and _typ(toks, i - 1) == "NUM":
            mag = toks[i - 1]
        if cue["kind"] == "save":
            j = i + 1
            while _typ(toks, j) == "FILLER":
                j += 1
            if _typ(toks, j) == "NUM":
                mag = toks[j]
        money_mag = bool(mag and mag["money"])
        if cue["explicit"] and self._budget_follows(i):
            keys, end = [self.table["cost_key"]], None     # "exceed the budget"
        else:
            keys, end = self._keys(i, default_cost=money_mag or cue["kind"] == "save")
        # "to 9" / "by 2.21" after the column name
        target = None
        if end is not None:
            if _typ(toks, end + 1) == "TO" and _typ(toks, end + 2) == "NUM":
                target = toks[end + 2]
            elif _typ(toks, end + 1) == "BY" and _typ(toks, end + 2) == "NUM":
                mag = toks[end + 2]

        subject, ref = None, None
        # "from TRANSFER to HYBRID"
        for k in range(len(toks) - 2):
            if (toks[k]["t"] == "FROM" and toks[k + 1]["t"] == "CODE"
                    and toks[k + 2]["t"] == "TO" and _typ(toks, k + 3) == "CODE"):
                subject = [toks[k + 3]["code"]]
                ref = {"kind": "codes", "codes": [toks[k + 1]["code"]]}
                break
        used = set()
        if subject is None:
            # "lower for HYBRID than for WAIT": the subject may follow the word
            subject, used = self.subject_for(i, allow_after=True)
        if not subject:
            raise _Unverifiable(f"no option found as the subject of {cue['raw']!r}")

        if ref is None and cue["explicit"]:
            ref, _ = _parse_ref(toks, i + 1, None)
            if ref is None:
                raise _Unverifiable(f"nothing to compare with after {cue['raw']!r}")
        if ref is None:
            k = i + 1
            while k < len(toks) and (k in used or toks[k]["t"] not in
                                     ("CODE", "STAR", "THAN")):
                k += 1
            if _typ(toks, k) == "THAN":
                ref = self.than_ref.get(k)
                if ref is None:
                    raise _Unverifiable("cannot read what follows 'than'")
        if ref is None:
            for ci, cref, cused in sorted(self.compare_refs, key=lambda c: abs(c[0] - i)):
                if not (cused & used) and cref["kind"] != "num":
                    ref = cref
                    break
        if ref is None and self.last and self.last[0] == subject:
            ref = {"kind": "codes", "codes": self.last[1]}
        if ref is None:
            if self.star and self.star not in subject:
                ref = {"kind": "codes", "codes": [self.star]}
            elif len(self.rows) == 2 and len(subject) == 1:
                ref = {"kind": "codes", "codes": [c for c in self.rows if c not in subject]}
            else:
                raise _Unverifiable(f"no option to compare with for {cue['raw']!r}")

        ref_codes = self._resolve_ref(ref, subject)
        for key in keys:
            d = self._direction(cue, key)
            for s in subject:
                vs = self.val(s, key)
                if target is not None and not _close(vs, target):
                    raise _Wrong(f"{s} {key} is {vs:g}, not {target['raw']}")
                if ref_codes is None:
                    if mag is not None:
                        raise _Unverifiable("a difference against a fixed number")
                    if ref["kind"] == "budget":
                        if key != self.table["cost_key"]:
                            raise _Unverifiable("budget compared with a non-cost column")
                        vr = self.budget_value(ref.get("amount"))
                    else:
                        vr = ref["tok"]["value"]
                    self._compare(s, key, vs, "the stated number", vr, d, neg)
                    continue
                for r in ref_codes:
                    vr = self.val(r, key)
                    self._compare(s, key, vs, r, vr, d, neg)
                    if mag is not None and not _close(abs(vs - vr), mag, loose=True):
                        raise _Wrong(f"{key}: {s} and {r} differ by {abs(vs - vr):g}, "
                                     f"not {mag['raw']}")
        if ref_codes is not None:
            self.last = (subject, ref_codes)

    def _budget_follows(self, i):
        j = i + 1
        while _typ(self.toks, j) in ("FILLER", "FUNC"):
            j += 1
        t = _typ(self.toks, j)
        return t == "BUDGET" or (t == "NUM" and self.toks[j]["money"])

    @staticmethod
    def _compare(s, key, vs, r, vr, d, neg):
        holds = vs > vr if d > 0 else vs < vr
        if holds == neg:
            word = "higher" if d > 0 else "lower"
            raise _Wrong(f"{key}: {s} ({vs:g}) is {'' if neg else 'not '}{word} "
                         f"than {r} ({vr:g})")

    def _bound(self, i, k):
        """Is the limit at token k part of the superlative at token i?
        Only when no and/or/but (and, after the superlative, no other option)
        stands between them: "the most on-time orders within the budget" is
        bound, "the most on-time orders, and it is within the budget" is not."""
        lo, hi = min(i, k), max(i, k)
        for t in self.toks[lo + 1:hi]:
            if t["t"] in ("AND", "OR") or t["raw"].lower() == "but":
                return False
            if k > i and t["t"] in ("CODE", "STAR", "CUE"):
                return False
        return True

    def _subset(self, i):
        """Rows the superlative at token i ranges over: all rows, or those
        inside a budget / 'at least N <column>' limit bound to it."""
        toks, codes = self.toks, list(self.rows)
        for k, t in enumerate(toks):
            if t["t"] == "BUDGETQ" and self._bound(i, k):
                b = self.budget_value(t.get("amount"))
                codes = [c for c in codes if self.val(c, self.table["cost_key"]) <= b]
                t["bound"] = True
        for k, t in enumerate(toks):
            if t["t"] != "QUAL" or _typ(toks, k + 1) != "NUM" or not self._bound(i, k):
                continue
            m = k + 2
            while _typ(toks, m) == "FILLER":
                m += 1
            if _typ(toks, m) != "METRIC" or len(toks[m]["keys"]) != 1:
                continue
            key, lim = toks[m]["keys"][0], toks[k + 1]["value"]
            if t["raw"].lower() == "at least":
                codes = [c for c in codes if self.val(c, key) >= lim]
            else:
                codes = [c for c in codes if self.val(c, key) <= lim]
        return codes

    def check_super(self, i):
        cue = self.toks[i]
        neg = self.negated(i)
        subject, _ = self.subject_for(i, allow_after=True)
        chains, _end = self.metric_for(i)
        if chains is None:
            # "the best option" with no column: accepted only for the option the
            # engine itself recommends.
            if cue["val"] and cue["dir"] > 0 and not neg and self.star \
                    and subject == [self.star]:
                return
            raise _Unverifiable(f"no column found for {cue['raw']!r}")
        self.cue_keys[i] = chains
        if not subject:
            raise _Unverifiable(f"no option found as the subject of {cue['raw']!r}")
        pool = self._subset(i)
        for key in [k for ks in chains for k in ks]:
            d = self._direction(cue, key)
            vals = [self.val(c, key) for c in pool]
            if not vals:
                raise _Unverifiable("no option inside the stated limit")
            ext = max(vals) if d > 0 else min(vals)
            for s in subject:
                is_ext = s in pool and self.val(s, key) == ext
                if is_ext == neg:
                    word = "highest" if d > 0 else "lowest"
                    raise _Wrong(f"{key}: {s} is {'' if neg else 'not '}the {word} "
                                 f"({word} is {ext:g})")

    def check_equal(self, i):
        if self.negated(i):
            raise _Unverifiable("negated 'same'")
        keys, _ = self._keys(i)
        codes = list(dict.fromkeys(t["code"] for t in self.toks if t["t"] == "CODE"))
        if self.star and any(t["t"] == "STAR" for t in self.toks) and self.star not in codes:
            codes.append(self.star)
        if len(codes) < 2:
            raise _Unverifiable("'same' without two options")
        for key in keys:
            vals = {self.val(c, key) for c in codes}
            if len(vals) != 1:
                raise _Wrong(f"{key} is not the same for {', '.join(codes)}")

    def check_range(self, i):
        toks = self.toks
        k = i - 1
        while k >= 0 and toks[k]["t"] not in ("METRIC", "CUE", "UNVER"):
            k -= 1
        if _typ(toks, k) != "METRIC" or len(toks[k]["keys"]) != 1:
            raise _Unverifiable("no single column found for the range")
        key = toks[k]["keys"][0]
        nums, j = [], i + 1
        while j < len(toks) and toks[j]["t"] not in ("CUE", "UNVER") and len(nums) < 2:
            if toks[j]["t"] == "NUM":
                code, m = None, j + 1
                while _typ(toks, m) in ("FUNC", "FILLER"):
                    m += 1
                if _typ(toks, m) == "CODE":
                    code = toks[m]["code"]
                nums.append((toks[j], code))
            j += 1
        if len(nums) != 2:
            raise _Unverifiable("range without two numbers")
        vals = [self.val(c, key) for c in self.rows]
        lo, hi = min(vals), max(vals)
        a, b = nums
        if not ((_close(lo, a[0]) and _close(hi, b[0]))
                or (_close(hi, a[0]) and _close(lo, b[0]))):
            raise _Wrong(f"{key} runs from {lo:g} to {hi:g}, "
                         f"not {a[0]['raw']} to {b[0]['raw']}")
        for tok, code in nums:
            if code is not None and not _close(self.val(code, key), tok):
                raise _Wrong(f"{key} of {code} is {self.val(code, key):g}, not {tok['raw']}")

    def check_within_budget(self, i):
        b = self.budget_value(self.toks[i].get("amount"))
        if any(t["t"] == "CUE" and t["kind"] == "super" and self._bound(k, i)
               for k, t in enumerate(self.toks)):
            return                         # the limit of a superlative
        subject, _ = self.subject_for(i)
        if not subject:
            return                         # no option named: nothing to compare
        neg = self.negated(i)
        for s in subject:
            inside = self.val(s, self.table["cost_key"]) <= b
            if inside == neg:
                raise _Wrong(f"{s} is {'' if neg else 'not '}within the budget of {b:g}")


# ── public ───────────────────────────────────────────────────────────────────

def check_sentence(sent: str, table: dict, star=None, budget=None) -> tuple:
    """-> ("ok" | "wrong" | "unverifiable", reason)."""
    try:
        _Sentence(sent, table, star, budget).check()
    except _Wrong as exc:
        return "wrong", str(exc)
    except _Unverifiable as exc:
        return "unverifiable", str(exc)
    return "ok", ""


def check_comparisons(text: str, table: dict, star=None, budget=None) -> tuple:
    """Check every sentence of ``text``.

    Returns (ok, reason).  ok is False when a comparison is wrong OR cannot be
    confirmed against the table.
    """
    for sent in _sentences(text):
        status, why = check_sentence(sent, table, star, budget)
        if status != "ok":
            return False, f"{status}: {why}"
    return True, "ok"


# ── tables ───────────────────────────────────────────────────────────────────

_ON_TIME = (r"on[- ]time orders?(?: count)?|on[- ]time deliver(?:y|ies)|"
            r"orders? (?:(?:would be|will be|are|is|being|delivered|kept) )?on[- ]time")
_PRIO = (r"priority[- ]1 on[- ]time(?: orders?)?|"
         r"priority[- ]1 orders?(?: (?:(?:would be|will be|are|being|delivered) )?on[- ]time)?")
_LATE = r"late orders?|orders? (?:(?:would be|will be|are|is|being) )?late"


def recommendation_table(rows: list) -> dict:
    """Comparison table for the recommendation / comparison views."""
    data, aliases = {}, []
    for r in rows:
        late = r.get("late_orders")
        data[r["code"]] = {
            "on_time_orders": r["on_time_orders"],
            "priority_on_time": r["priority_on_time"],
            "total_days_late": r["total_days_late"],
            "extra_cost": r["extra_cost"],
            "late_count": r["total_orders"] - r["on_time_orders"],
            "max_delay": (max([o["days_late"] for o in late] or [0])
                          if late is not None else None),
        }
        aliases.append((r["code"], r["code"]))
        if r.get("name"):
            aliases.append((r["name"], r["code"]))
    return {
        "rows": data,
        "aliases": aliases,
        "cost_key": "extra_cost",
        "metrics": [
            (_PRIO, ["priority_on_time"]),
            (_ON_TIME, ["on_time_orders"]),
            (r"total days late|days late", ["total_days_late"]),
            (r"(?:maximum|max|longest) delay", ["max_delay"]),
            (_LATE, ["late_count"]),
            (r"extra costs?|costs?", ["extra_cost"]),
        ],
        "better": {"on_time_orders": +1, "priority_on_time": +1,
                   "total_days_late": -1, "extra_cost": -1,
                   "late_count": -1, "max_delay": -1},
    }


def world_risk_table(rows: list, has_focus: bool) -> dict:
    """Comparison table for the world-risk view.  Values are rounded the way
    the view prints them, so a claim is judged against what the user sees."""
    data, aliases = {}, []
    for r in rows:
        data[r["code"]] = {
            "extra_cost": r["extra_cost"],
            "expected_late_orders": round(r["expected_late_orders"], 2),
            "p90_late_orders": r["p90_late_orders"],
            "tail_mean_late_orders": round(r["tail_mean_late_orders"], 2),
            "p_no_late_pct": round(r["p_no_late_pct"], 1),
            "late_at_focus": r.get("late_at_focus") if has_focus else None,
            "average_range": None,
        }
        aliases.append((r["code"], r["code"]))
        if r.get("name"):
            aliases.append((r["name"], r["code"]))
    # "late orders" alone does not say which column: the claim must hold in all.
    plain = ["expected_late_orders", "p90_late_orders", "tail_mean_late_orders"]
    if has_focus:
        plain.append("late_at_focus")
    return {
        "rows": data,
        "aliases": aliases,
        "cost_key": "extra_cost",
        "metrics": [
            (r"range of the average", ["average_range"]),
            (r"worst[- ]10% average", ["tail_mean_late_orders"]),
            (r"90th percentile(?: of late orders)?", ["p90_late_orders"]),
            (r"chance of no late orders?|chance", ["p_no_late_pct"]),
            (r"expected (?:number of )?late orders?|expected late|expected value",
             ["expected_late_orders"]),
            (r"late if it arrives(?: on)? " + _MONTH + r" \d{1,2}",
             ["late_at_focus"]),
            (_LATE, plain),
            (r"extra costs?|costs?", ["extra_cost"]),
        ],
        "better": {"extra_cost": -1, "expected_late_orders": -1,
                   "p90_late_orders": -1, "tail_mean_late_orders": -1,
                   "p_no_late_pct": +1, "late_at_focus": -1},
    }
