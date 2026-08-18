"""Standing tests for the pre-flight question linter (D83).

Cairn's other checks run on the way out. This one runs on the way in, because D82
measured that eleven of thirteen unmatched query terms were vocabulary the document
does not use — and those queries did not fail loudly, they ranked nothing and looked
like an answer-free corpus.
"""

from __future__ import annotations

import pytest

from cairn.question_lint import (
    ABSENT_TERMS,
    ADJUDICATION,
    COMPOUND,
    NO_LOCATOR,
    lint,
)

pytestmark = pytest.mark.layer0

VOCAB = frozenset("the system includes a separator and watt magnetrons for treating "
                  "solid waste claim treatment module".split())


def _kinds(findings):
    return [f.kind for f in findings]


def test_terms_no_passage_contains_are_named():
    """The D82 finding, made actionable: "wattage" against "400 Watt magnetrons" ranked
    nothing and said nothing. Naming the word that missed is the whole value."""
    f = lint("What wattage do the magnetrons use?", vocabulary=VOCAB)
    absent = next(x for x in f if x.kind == ABSENT_TERMS)
    assert "wattage" in absent.terms
    assert "magnetrons" not in absent.terms      # this one IS in the corpus


def test_pronouns_are_not_reported_as_missing_vocabulary():
    """A document has no reason to contain "them". Reporting it as a missing term is
    noise that trains the reader to skip the finding."""
    f = lint("Who manufactures them?", vocabulary=VOCAB)
    absent = next(x for x in f if x.kind == ABSENT_TERMS)
    assert "them" not in absent.terms


def test_the_pronoun_list_is_the_linters_own_not_retrievals():
    """Widening `retrieval.STOPWORDS` would move every BM25 score and the calibration
    fitted to them (D82). A cosmetic fix to a linter must not become a silent retrieval
    change."""
    from cairn.retrieval import STOPWORDS
    assert "them" not in STOPWORDS


def test_a_unit_the_document_lacks_is_flagged():
    from cairn.locator import Unit
    units = [Unit("claim 1", "D", 0, 10, None)]
    assert NO_LOCATOR in _kinds(lint("What does claim 99 recite?", units=units))
    assert NO_LOCATOR not in _kinds(lint("What does claim 1 recite?", units=units))


def test_a_request_for_a_legal_conclusion_is_flagged_before_the_search_runs():
    """Knowing beforehand is worth saying: the honest outcome is a refusal that hands
    over what was found (D10/D22), and the asker may want to rephrase toward what Cairn
    can actually do."""
    assert ADJUDICATION in _kinds(lint("Is claim 1 patentable over the cited art?"))
    assert ADJUDICATION in _kinds(lint("Does this infringe the '133 patent?"))
    assert ADJUDICATION not in _kinds(lint("What does claim 1 recite?"))


def test_two_questions_in_one_are_flagged_not_split():
    """`partial` exists to answer this honestly, but asking separately gives each half
    its own evidence and its own outcome."""
    assert COMPOUND in _kinds(
        lint("What wattage magnetrons are used, and who manufactures them?"))
    # A bare "and" joining noun phrases is not two questions.
    assert COMPOUND not in _kinds(lint("What are the solid and liquid treatment modules?"))


def test_the_linter_never_rewrites_the_question():
    """The question as asked is what gets answered and recorded — a rewrite would change
    what was asked, and the Record of Inquiry has to show the original. Every finding is
    an annotation, so nothing it returns is a replacement question."""
    q = "What wattage do the magnetrons use?"
    for f in lint(q, vocabulary=VOCAB):
        assert q not in f.message           # no echoed "did you mean" restatement
        assert all(t in q.lower() for t in f.terms)


def test_a_clean_question_produces_nothing():
    """Silence is the common case, and a linter that always says something is one a
    reviewer learns to ignore."""
    assert lint("What does the separator claim?", vocabulary=VOCAB) == []
