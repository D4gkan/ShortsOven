"""
text_cleanup.py
----------------
Two offline cleanup passes applied to every OCR line before narration:

1. Username stripping (`remove_usernames`) -- Reddit screenshots are
   full of handles like "u/avc12" or "abc_ss_asdf" that read out loud
   terribly and add no value to narration. We detect and drop them
   token by token:
     - any token containing an underscore -> username
       (abc_ss_asdf, abfdsdfg_123, abb_csa)
     - any token that mixes letters AND digits together -> username
       (avc12, av12c, as243svd)
   Ordinary numeric phrases are naturally safe because they're
   separate tokens rather than one merged alphanumeric blob, e.g.
   "12 pm", "12 am", "12 $", "iphone 16" each split into a
   pure-number token and a pure-word token -- neither one mixes
   letters and digits *within the same token*, so neither gets
   flagged. A small whitelist additionally protects extremely common
   merged forms (e.g. "8am", "1st", "16gb", "1080p", "90s") in case a
   screenshot happens to render them without a space.

2. Spelling correction (`clean_text`) -- SymSpell fixes minor OCR
   mistakes (e.g. "Thls" -> "This") on whatever real words remain.
"""

import os
import re
import string
from typing import List

from .logger_setup import get_logger
from .ocr_engine import TextLine

log = get_logger(__name__)

_SYMSPELL = None

# Punctuation we trim off the edges of a token before inspecting it
# (but we deliberately keep '$', '%', '_' since those are meaningful
# for the checks below).
_EDGE_PUNCT = ''.join(c for c in string.punctuation if c not in "$%_")

# Merged alphanumeric forms that are common, legitimate, and NOT
# usernames, even though they mix letters and digits in one token.
_USERNAME_WHITELIST_PATTERNS = [
    r'^\d{1,2}(am|pm)$',                      # 8am, 12pm
    r'^\d+(st|nd|rd|th)$',                    # 1st, 2nd, 3rd, 21st
    r'^\d+(gb|mb|tb|kb|k|hz|ghz|mhz)$',       # 16gb, 4k, 5ghz
    r'^\d{3,4}p$',                            # 1080p, 720p
    r'^\d+(mm|cm|km|ft|lb|kg|oz)$',           # 35mm, 5km, 10kg
    r'^\d+[dgx]$',                            # 3d, 5g, 2x
    r'^\d{2,4}s$',                            # 90s, 80s, 2000s
    r'^(iphone|ipad|macbook|imac|airpods|windows|android|xbox|'
    r'playstation|ps|gpt|chatgpt|wifi|covid|gen|season|episode|'
    r'chapter|page|level|round|part|room|class|grade|floor|'
    r'day|week|month|year)\d+$',              # iphone16, gpt4, day30
]
_USERNAME_WHITELIST = [re.compile(p, re.IGNORECASE) for p in _USERNAME_WHITELIST_PATTERNS]

# Common informal/slang words and contraction fragments that show up
# constantly in Reddit text and are NOT OCR mistakes -- SymSpell's
# dictionary is formal English, so it doesn't recognize these and
# "corrects" them to the nearest formal word instead (e.g. "lil" ->
# "oil", "cuz" -> "cut"). We skip spell-correction for anything in
# this list rather than let SymSpell silently rewrite intentional
# slang into the wrong word.
_SLANG_WHITELIST = {
    "lil", "cuz", "cause", "coz", "gonna", "wanna", "gotta", "kinda",
    "sorta", "dunno", "lemme", "gimme", "hafta", "outta", "tryna",
    "y'all", "yall", "ain't", "aint", "ur", "u", "im", "dont", "cant",
    "wont", "isnt", "wasnt", "didnt", "couldnt", "wouldnt", "shouldnt",
    "ok", "okay", "yeah", "yep", "nah", "nope", "bro", "sis", "fam",
    "lol", "lmao", "omg", "wtf", "tbh", "fyi", "asap", "af", "rn",
    "fr", "ngl", "smh", "idk", "imo", "imho", "btw", "til",
}


def _is_username_token(token: str) -> bool:
    """A word is treated as a username if it has an underscore, or if
    it mixes letters and digits together within the same token (and
    isn't one of the common whitelisted exceptions like '8am')."""
    core = token.strip(_EDGE_PUNCT)
    if not core:
        return False

    if "_" in core:
        return True

    has_digit = any(c.isdigit() for c in core)
    has_alpha = any(c.isalpha() for c in core)
    if not (has_digit and has_alpha):
        return False  # pure number ("12", "$12", "100%") or pure word -> safe

    if any(pat.match(core) for pat in _USERNAME_WHITELIST):
        return False

    return True


def remove_usernames(text: str) -> str:
    """Strips username-like tokens out of a line of text so they're
    never sent to narration."""
    tokens = text.split(" ")
    kept = [t for t in tokens if t.strip() and not _is_username_token(t)]
    removed = [t for t in tokens if t.strip() and _is_username_token(t)]
    if removed:
        log.info(f"Removed username-like token(s): {', '.join(removed)}")
    return " ".join(kept).strip()


def _find_symspell_dictionary() -> str:
    """Locate SymSpell's bundled frequency dictionary without relying
    on the deprecated/removed `pkg_resources` package."""
    try:
        import importlib.resources as importlib_resources
        candidate = importlib_resources.files("symspellpy").joinpath(
            "frequency_dictionary_en_82_765.txt"
        )
        if candidate.is_file():
            return str(candidate)
    except Exception:
        pass

    try:
        import symspellpy
        candidate = os.path.join(
            os.path.dirname(os.path.abspath(symspellpy.__file__)),
            "frequency_dictionary_en_82_765.txt",
        )
        if os.path.exists(candidate):
            return candidate
    except Exception:
        pass

    return ""


def _get_symspell():
    global _SYMSPELL
    if _SYMSPELL is None:
        try:
            from symspellpy import SymSpell
            sym = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
            dict_path = _find_symspell_dictionary()
            if dict_path:
                sym.load_dictionary(dict_path, term_index=0, count_index=1)
                _SYMSPELL = sym
            else:
                log.warning("Could not locate SymSpell's frequency dictionary; "
                            "skipping automatic OCR-error cleanup.")
                _SYMSPELL = False
        except Exception as e:
            log.warning(f"Spell-correction dictionary unavailable ({e}); "
                        f"skipping automatic OCR-error cleanup.")
            _SYMSPELL = False
    return _SYMSPELL


def _fix_word(word: str, sym) -> str:
    if not word.isalpha() or len(word) < 4:
        return word
    if word.lower() in _SLANG_WHITELIST:
        return word

    # All-caps tokens (ADHD, OCR, DIY, ...) are almost always acronyms
    # or initialisms rather than OCR typos of a formal-dictionary word.
    # SymSpell has no notion of "acronym" so it happily "corrects"
    # ADHD -> ADD; just leave all-caps tokens alone entirely.
    if word.isupper():
        return word

    from symspellpy import Verbosity
    suggestions = sym.lookup(word.lower(), Verbosity.CLOSEST, max_edit_distance=2)
    if not suggestions:
        return word
    best = suggestions[0]

    # Capitalized words (Aquaman, Reddit, Karen, ...) are frequently
    # proper nouns that legitimately aren't in a formal dictionary,
    # rather than misspellings. A distance-2 "fix" can swap out enough
    # letters to land on a totally different word (Aquaman -> Andaman).
    # Proper nouns are usually typed correctly by OCR since they're
    # rendered in the same font as everything else, so we only accept
    # very close (distance-1) matches for them, and leave anything
    # further away as-is rather than guessing.
    if word[0].isupper() and best.distance > 1:
        return word

    # Preserve original capitalization style
    if word[0].isupper():
        return best.term.capitalize()
    return best.term


def clean_text(text: str) -> str:
    sym = _get_symspell()
    if not sym:
        return text
    # [^\W\d_] matches any unicode letter (not just A-Za-z), so accented
    # words like "fiancé" or "café" are captured as a single token
    # instead of splitting at the accented character.
    tokens = re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)*|[\d\W]+", text)
    fixed = [_fix_word(t, sym) if re.match(r"^[A-Za-z']+$", t) else t for t in tokens]
    return "".join(fixed)


def clean_lines(lines: List[TextLine]) -> List[TextLine]:
    """Applies username stripping + OCR-error cleanup to every
    detected line. Lines that consist ENTIRELY of a username (and
    therefore become empty after stripping) are dropped from the
    list entirely -- there's nothing left to narrate or reveal, and
    passing empty text to Piper crashes its WAV writer with
    '# channels not specified'."""
    cleaned_lines = []
    for line in lines:
        no_usernames = remove_usernames(line.text)
        cleaned = clean_text(no_usernames)

        if not cleaned.strip():
            log.info(f"Line {line.index}: '{line.text}' -> (empty after cleanup, "
                      f"dropping this line)")
            continue

        if cleaned != line.text:
            log.info(f"Line {line.index}: '{line.text}' -> '{cleaned}'")
        line.text = cleaned
        cleaned_lines.append(line)

    if not cleaned_lines:
        log.warning("All OCR lines were removed during cleanup (usernames only?); "
                    "nothing left to narrate.")
    return cleaned_lines