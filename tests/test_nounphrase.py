"""Standing tests for noun-phrase reduction of element names (D80).

`reference_numerals` takes the words before a numeral as its element name, and 22% /
24% of those names on the two engagement patents were not names but sentence fragments.
English noun phrases are head-final, so the phrase is read right to left, collecting
modifiers until a word that cannot be one.
"""

from __future__ import annotations

import pytest

from cairn.nounphrase import head_phrase, is_name

pytestmark = pytest.mark.layer0


@pytest.mark.parametrize(("raw", "want"), [
    ("and clothes washer", "clothes washer"),        # tail of a list
    ("or signal lines", "signal lines"),
    ("by a motor", "motor"),                         # stranded preposition + determiner
    ("to the operation", "operation"),
    ("as a chip", "chip"),
    ("includes a memory", "memory"),                 # verb head
    ("including electrolysis plates", "electrolysis plates"),
    ("by broken line", "broken line"),
    ("dosing siphon", "dosing siphon"),              # already a name — untouched
])
def test_a_fragment_reduces_to_the_name_inside_it(raw, want):
    assert head_phrase(raw) == want


def test_adjectives_and_their_adverbs_are_kept():
    """They modify the head and belong in the name — only closed-class words end the
    phrase, so "substantially cylindrical" survives where "of" would not."""
    assert head_phrase("substantially cylindrical holding tank") == \
        "substantially cylindrical holding tank"


@pytest.mark.parametrize(("raw", "want"), [
    ("through primary and secondary liquid outlet pipes respectively",
     "primary and secondary liquid outlet pipes"),
    ('ceramic particulate "scrubber" or filter',
     'ceramic particulate "scrubber" or filter'),
])
def test_a_coordinated_head_survives_the_conjunction(raw, want):
    """A coordinated head is a real element name in patent prose. Truncating at the
    conjunction would trade one bad name for a narrower bad name — so the phrase
    continues through "and"/"or" when there is a content word on the left."""
    assert head_phrase(raw) == want


def test_a_phrase_naming_nothing_returns_nothing():
    """"include a" names no thing. Returning "" lets the caller say the parser found no
    element, rather than shipping an empty label as though it were one."""
    assert head_phrase("include a") == ""
    assert not is_name("include a")


def test_the_residue_is_judged_by_shape_not_by_length():
    """A word count flagged long-but-good names and passed short broken ones — it
    measured the wrong property."""
    assert is_name("primary and secondary liquid outlet pipes")   # 6 words, fine
    assert not is_name("by a")                                    # 2 words, not a name


def test_a_hyphenated_compound_is_not_a_reference_numeral():
    """"a 36-pin connector" is a compound modifier. Extracting 36 as a part invented a
    numeral the patent does not have — found because the noun-phrase reduction left
    "include a" as the single residue across both patents."""
    from cairn.patents import reference_numerals
    text = ("DESCRIPTION\nThe device 100 may include a 36-pin connector and a "
            "12-volt supply.\n\nWhat is claimed is:\n\n1. A system.\n")
    nums = {n.number for n in reference_numerals(text)}
    assert "100" in nums
    assert "36" not in nums and "12" not in nums
