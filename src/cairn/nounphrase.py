"""nounphrase — isolate the noun phrase an element name actually is (D80).

The problem, measured. `reference_numerals` takes the words before a numeral as its
element name, and on the two engagement patents 22% and 24% of those names are not
names: "and clothes washer", "by a motor", "include a", "to the operation", "through
primary and secondary liquid outlet pipes respectively". A reviewer reads these in the
legend and in the interpretation queue, so a name that is really a sentence fragment is
a small, constant tax on every glance.

**Why rules and not a tagger.** The failures above are shallow — leading conjunctions,
stranded prepositions, verb heads — and a closed-class rule fixes them in a way whose
mistakes are readable *in the rule*. A statistical tagger is deterministic enough for
the contract (frozen model, no sampling), but its errors are opaque, and this output
feeds a locate-and-evidence surface a professional relies on. The residue a tagger
would genuinely add — coordination and appositives — is measurable after this, which
is the point: take the dependency on evidence, not on the shape of the problem.

**The one structural fact this leans on.** English noun phrases are head-final: the
thing being named is the last word, and everything before it modifies it. So the phrase
is read RIGHT to LEFT, collecting modifiers until a word that cannot be one.
"""

from __future__ import annotations

import re

# Words that cannot be part of an element's name, and so end the phrase when walking
# leftward. Deliberately closed classes — determiners, prepositions, and the copular /
# structural verbs patent prose runs on. Adjectives and adverbs are NOT here: "primary",
# "substantially cylindrical" and the like modify the head and belong in the name.
_DETERMINER = {"a", "an", "the", "said", "this", "that", "these", "those", "its",
               "their", "his", "her", "each", "any", "some", "such", "one"}
_PREPOSITION = {"of", "in", "on", "at", "to", "for", "with", "from", "into", "onto",
                "through", "by", "near", "under", "over", "between", "within", "about",
                "across", "along", "around", "against", "toward", "towards", "upon",
                "beneath", "below", "above", "beside", "per", "via", "during"}
_VERBAL = {"is", "are", "was", "were", "be", "being", "been", "has", "have", "had",
           "having", "include", "includes", "included", "including", "comprise",
           "comprises", "comprised", "comprising", "consist", "consists", "consisting",
           "provide", "provides", "provided", "providing", "dispose", "disposed",
           "mount", "mounted", "connect", "connected", "couple", "coupled", "define",
           "defines", "defined", "extend", "extends", "extending", "position",
           "positioned", "locate", "located", "attach", "attached", "form", "formed",
           "shown", "illustrated", "indicated", "designated", "denoted", "depicted",
           "receive", "receives", "received", "carry", "carries", "carried", "use",
           "uses", "used", "utilize", "utilizes", "operate", "operates", "operated",
           "wherein", "whereby", "which", "where", "when", "than", "as", "so", "if",
           "further", "also", "thus", "however", "therefore", "then"}
_CONJUNCTION = {"and", "or", "nor", "but", "plus"}

_STOP = _DETERMINER | _PREPOSITION | _VERBAL

# Trailing words that are never the head: sentence adverbs and stray discourse markers.
# ("respectively" is the one that actually occurs; the rest are cheap insurance.)
_TRAILING = {"respectively", "therein", "thereof", "thereto", "therefrom", "hereinafter",
             "above", "below", "accordingly", "generally", "typically", "preferably",
             "optionally", "instead", "again", "only", "also", "too"}

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9\-]*")


def _key(word: str) -> str:
    return word.strip("\"'()[].,;:").lower()


def head_phrase(phrase: str) -> str:
    """The noun phrase inside a candidate element name — head noun plus its modifiers.

    Returns "" when there is no noun to name (``"include a"`` names nothing), which the
    caller should treat as "the parser found no element here", not as an empty label.

    Coordination is preserved when both sides are content words — "primary and secondary
    liquid outlet pipes", 'ceramic particulate "scrubber" or filter' — because a
    coordinated head is a real element name in patent prose, and truncating at the
    conjunction would replace one bad name with a narrower bad name. A conjunction with
    nothing contentful to its left is simply dropped: "and clothes washer" is the tail of
    a list, not a coordination.
    """
    words = [w for w in phrase.split() if _WORD.search(w)]
    while words and _key(words[-1]) in _TRAILING:
        words.pop()
    if not words:
        return ""

    kept: list[str] = []
    i = len(words) - 1
    while i >= 0:
        k = _key(words[i])
        if k in _CONJUNCTION:
            # Look left: a content word there means this is a coordinated head and the
            # phrase continues through it. Nothing (or a stop word) means the phrase
            # began mid-list, and the conjunction is not part of the name.
            prev = _key(words[i - 1]) if i else ""
            if prev and prev not in _STOP and prev not in _CONJUNCTION:
                kept.append(words[i])
                i -= 1
                continue
            break
        if k in _STOP:
            break
        kept.append(words[i])
        i -= 1

    kept.reverse()
    while kept and _key(kept[-1]) in _CONJUNCTION:   # a dangling "and" is not a head
        kept.pop()
    return " ".join(kept).strip()


def is_name(phrase: str) -> bool:
    """Whether a phrase reads as an element NAME rather than a fragment of a sentence.

    Used to flag what the chunker could not rescue, so the residue is visible and
    countable instead of quietly shipping as a label.
    """
    p = head_phrase(phrase)
    return bool(p) and _key(p.split()[-1]) not in _STOP | _CONJUNCTION
