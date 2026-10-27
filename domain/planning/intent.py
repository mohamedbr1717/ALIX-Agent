"""Multi-step intent detection (Decision 1 — pure domain).

Post-E2E fix (spec amendment §4.1, 2026-10-27): the original
trigger for plan creation was endurance only — the ReAct loop
had to ENTER its third round still unfinished before code handed
the task to the plan executor. The live acceptance run proved
that assumption false: a fast model batches a 4-step ordered
task into one or two rounds and answers, so planning was never
invoked at all (no plan file, no audit event). This module is
the intent-first half of the corrected trigger: a deterministic,
pure function that recognises a request as STRUCTURALLY
multi-step before any execution, so run() can offer it to the
plan path first. The endurance escalation remains as the safety
net for whatever this detector misses.

The detector is deliberately CONSERVATIVE. A false negative is
cheap (the endurance net, then plain ReAct, still serve the
request); a false positive costs one plan attempt that the
controller may decline — but it still changes the conversation,
so the rules below require explicit structural evidence, never
a single weak word. No rule looks at meaning, verbs or topics —
only at sequencing structure the user themselves wrote:

Rule A — ordering connectors (``connectors``)
    Count explicit ordering connectors (Arabic: اولا … ثم …
    بعد ذلك … اخيرا; English: first … then … finally …).
    Fires when there are >= 3 hits, OR >= 2 hits of which at
    least one is an opener (اولا / first) or a closer
    (اخيرا / finally). A lone «ثم» — or a lone «أولًا» in a
    greeting — never fires.

Rule B — enumerated steps (``enumeration``)
    Step markers with values: ``1.`` / ``2)`` at a segment
    start, Arabic-Indic numerals (١. ٢.), or explicit labels
    (``step 1`` / «الخطوة ١»). Only values 1..9 count, so
    dates (27.10) and times (10:00) cannot pose as steps.
    Fires when the markers contain an ascending consecutive
    pair (k, k+1) in order, or >= 3 strictly ascending values.

Rule C — explicit sequencing instruction (``explicit_order``)
    A direct instruction to execute in sequence
    («نفّذ بالترتيب», "in order", "step by step", …) AND at
    least two commas (ASCII or Arabic) separating segments —
    the instruction alone might govern one step's internals;
    the commas evidence multiple segments to sequence.

Arabic text is normalised before matching (diacritics and
tatweel stripped; أ/إ/آ -> ا; ة -> ه; ى -> ي; ئ -> ي) so the
connector lists below are written in their normalised forms.
Matching is whole-phrase: a connector glued inside a longer
word never counts.

This module is pure: no I/O, no clock, no LLM. It also does
NOT decide routing precedence — research requests keep their
earlier branch in run(); the detector is only evaluated after
that branch, by the caller.
"""
from __future__ import annotations

import re
from typing import Optional

#: Rule names returned by multi_step_signals(), in report order.
SIGNAL_CONNECTORS = "connectors"
SIGNAL_ENUMERATION = "enumeration"
SIGNAL_EXPLICIT_ORDER = "explicit_order"

# ------------------------------------------------------------------
# Normalisation
# ------------------------------------------------------------------

#: Arabic diacritics (tanween U+064B–U+0652: harakat, shadda,
#: …), tatweel/kashida (U+0640), superscript alef (U+0670) —
#: removed before matching.
_DIACRITICS_RE = re.compile("[ـً-ْٰ]")

_CHAR_MAP = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ة": "ه",
        "ى": "ي",
        "ئ": "ي",
        "ؤ": "و",
    }
)


def _normalize(text: str) -> str:
    """Strip Arabic diacritics and unify letter variants, then
    lowercase (affects Latin script only)."""
    text = _DIACRITICS_RE.sub("", text)
    return text.translate(_CHAR_MAP).lower()


# ------------------------------------------------------------------
# Rule A — ordering connectors
# ------------------------------------------------------------------

#: Arabic connectors, in POST-normalisation form.
_AR_OPENERS = ("اولا", "في البدايه")
_AR_MIDDLES = (
    "ثم",
    "ثانيا",
    "ثالثا",
    "رابعا",
    "خامسا",
    "سادسا",
    "بعد ذلك",
    "بعدها",
    "بعديذ",
    "ومن ثم",
)
_AR_CLOSERS = ("اخيرا", "في النهايه")

#: English connectors, matched on the lowercased text.
_EN_OPENERS = ("first",)
_EN_MIDDLES = ("then", "after that", "afterwards", "next")
_EN_CLOSERS = ("finally", "lastly")

_AR_LETTER = r"ء-ي"


def _ar_phrase_re(phrase: str) -> "re.Pattern":
    return re.compile(
        r"(?<!["
        + _AR_LETTER
        + r"])"
        + re.escape(phrase)
        + r"(?!["
        + _AR_LETTER
        + r"])"
    )


def _en_phrase_re(phrase: str) -> "re.Pattern":
    return re.compile(r"\b" + re.escape(phrase) + r"\b")


def _count_group(normalized: str, phrases, pattern_fn) -> int:
    return sum(
        len(pattern_fn(phrase).findall(normalized))
        for phrase in phrases
    )


def _connectors_fire(normalized: str) -> bool:
    ar_open = _count_group(normalized, _AR_OPENERS, _ar_phrase_re)
    ar_mid = _count_group(normalized, _AR_MIDDLES, _ar_phrase_re)
    ar_close = _count_group(normalized, _AR_CLOSERS, _ar_phrase_re)
    en_open = _count_group(normalized, _EN_OPENERS, _en_phrase_re)
    en_mid = _count_group(normalized, _EN_MIDDLES, _en_phrase_re)
    en_close = _count_group(normalized, _EN_CLOSERS, _en_phrase_re)

    total = ar_open + ar_mid + ar_close + en_open + en_mid + en_close
    anchored = (ar_open + en_open + ar_close + en_close) > 0
    return total >= 3 or (total >= 2 and anchored)


# ------------------------------------------------------------------
# Rule B — enumerated steps
# ------------------------------------------------------------------

#: Arabic-Indic digits -> values.
_DIGIT_VALUES = {str(d): d for d in range(10)}
_DIGIT_VALUES.update(
    {chr(0x660 + d): d for d in range(10)}  # ٠١٢٣٤٥٦٧٨٩
)

#: "step 3" / «الخطوة ٣» labels (post-normalisation: الخطوه).
_LABEL_RE = re.compile(r"(?:step|الخطوه)\s*(\d+|[٠-٩]+)")

#: Numerals at a segment start, closed by '.' or ')' — ':' is
#: deliberately excluded so times (10:00) never match.
_SEGMENT_NUMERAL_RE = re.compile(
    r"(?:^|[\n\(\[،,؛;]\s*)(\d+|[٠-٩]+)\s*[.\)]"
)


def _marker_value(token: str) -> Optional[int]:
    value = 0
    for ch in token:
        digit = _DIGIT_VALUES.get(ch)
        if digit is None:
            return None
        value = value * 10 + digit
    return value


def _enumeration_fire(normalized: str) -> bool:
    values = []
    for match in _LABEL_RE.finditer(normalized):
        v = _marker_value(match.group(1))
        if v is not None and 1 <= v <= 9:
            values.append(v)
    for match in _SEGMENT_NUMERAL_RE.finditer(normalized):
        v = _marker_value(match.group(1))
        if v is not None and 1 <= v <= 9:
            values.append(v)

    if len(values) < 2:
        return False
    # An ascending consecutive pair, in order: 1..2, 2..3, …
    for i, v in enumerate(values):
        if v + 1 in values[i + 1 :]:
            return True
    # Or a strictly ascending run of three or more.
    ascending = 1
    for prev, cur in zip(values, values[1:]):
        ascending = ascending + 1 if cur > prev else 1
        if ascending >= 3:
            return True
    return False


# ------------------------------------------------------------------
# Rule C — explicit sequencing instruction + segments
# ------------------------------------------------------------------

#: Sequencing instructions, in POST-normalisation form.
_ORDER_INSTRUCTIONS = (
    "نفذ بالترتيب",
    "بالترتيب التالي",
    "حسب الترتيب",
    "خطوه بخطوه",
    "in order",
    "in sequence",
    "step by step",
)


def _explicit_order_fire(normalized: str) -> bool:
    if not any(p in normalized for p in _ORDER_INSTRUCTIONS):
        return False
    commas = normalized.count(",") + normalized.count("،")
    return commas >= 2


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def multi_step_signals(text) -> tuple:
    """Names of the rules that fire for ``text``, in the fixed
    order (connectors, enumeration, explicit_order). Empty
    tuple for non-string or empty input."""
    if not isinstance(text, str) or not text.strip():
        return ()
    normalized = _normalize(text)
    signals = []
    if _connectors_fire(normalized):
        signals.append(SIGNAL_CONNECTORS)
    if _enumeration_fire(normalized):
        signals.append(SIGNAL_ENUMERATION)
    if _explicit_order_fire(normalized):
        signals.append(SIGNAL_EXPLICIT_ORDER)
    return tuple(signals)


def is_multi_step_request(text) -> bool:
    """True when the request is STRUCTURALLY multi-step per the
    rules in this module's docstring. Pure and deterministic;
    routing precedence (research first) is the caller's job."""
    return bool(multi_step_signals(text))
