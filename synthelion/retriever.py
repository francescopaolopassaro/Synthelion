# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""BM25+ retrieval over arbitrary text chunks, with optional RM3 pseudo-relevance
feedback query expansion.

Ported from Caveman C# 1.4.1's CavemanRetriever. Ranks arbitrary text chunks
(sentences, conversation turns, JSON rows serialized to text, log lines, ...) against
a query using BM25+. `retrieve_with_feedback` additionally runs RM3 pseudo-relevance
feedback: an initial BM25 pass finds the top candidates, a "relevance model" is built
from their vocabulary, and the query is expanded with that model's top terms before a
second, final ranking pass — this finds relevant chunks that don't literally contain
the query's words but do contain words the top initial results have in common. Pure
term-frequency statistics; no external dependency, no model, no network call.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import regex

from synthelion.word_provider import FunctionWordProvider

_WORD_SPLIT = regex.compile(r"[\p{L}\p{M}\p{N}]+", regex.UNICODE)

_K1 = 1.5
_B = 0.75


@dataclass(frozen=True)
class RetrievalResult:
    """One retrieved document: its position in the input list, its text, and its score."""
    index: int
    document: str
    score: float


def _tokenize(text: str) -> list[str]:
    if not text or not text.strip():
        return []
    return [w.lower() for w in _WORD_SPLIT.findall(text)]


class Retriever:
    def __init__(
        self,
        word_provider: FunctionWordProvider | None = None,
        bm25_delta: float = 1.0,
        rm3_feedback_docs: int = 10,
        rm3_expansion_terms: int = 10,
        rm3_original_query_weight: float = 0.6,
    ) -> None:
        """bm25_delta: BM25+ lower-bound term added to every non-zero term match
        (default 1.0) — see json_crusher._bm25_select for the rationale.
        rm3_feedback_docs: number of top initial-pass documents used to build the
        RM3 relevance model (default 10). rm3_expansion_terms: number of expansion
        terms drawn from the relevance model (default 10).
        rm3_original_query_weight: weight given to the original query terms vs. the
        expansion terms in the second pass (default 0.6 = 60% original query, 40%
        expansion terms — the standard RM3 default)."""
        self._provider = word_provider
        self.bm25_delta = bm25_delta
        self.rm3_feedback_docs = rm3_feedback_docs
        self.rm3_expansion_terms = rm3_expansion_terms
        self.rm3_original_query_weight = rm3_original_query_weight

    def retrieve(self, documents: list[str], query: str, top_k: int) -> list[RetrievalResult]:
        """Ranks `documents` against `query` with plain BM25+ (single pass, no feedback)."""
        if not documents or not query or not query.strip() or top_k <= 0:
            return []

        tokenized_docs = [_tokenize(d) for d in documents]
        query_weights = _uniform_weights(_tokenize(query))
        if not query_weights:
            return []

        scores = self._compute_weighted_bm25(tokenized_docs, query_weights)
        return _rank_top_k(documents, scores, top_k)

    def retrieve_with_feedback(
        self, documents: list[str], query: str, top_k: int, iso3: str | None = None
    ) -> list[RetrievalResult]:
        """Ranks `documents` against `query` using BM25+, then RM3 pseudo-relevance
        feedback: expands the query with terms characteristic of the initial top
        results and re-ranks. Falls back to a plain `retrieve` pass when the initial
        pass finds no relevant document at all (nothing to build a relevance model
        from)."""
        if not documents or not query or not query.strip() or top_k <= 0:
            return []

        tokenized_docs = [_tokenize(d) for d in documents]
        original_terms = list(dict.fromkeys(_tokenize(query)))  # de-dup, preserve order
        if not original_terms:
            return []

        initial_weights = _uniform_weights(original_terms)
        initial_scores = self._compute_weighted_bm25(tokenized_docs, initial_weights)

        feedback = sorted(
            ((i, s) for i, s in enumerate(initial_scores) if s > 0),
            key=lambda item: item[1],
            reverse=True,
        )[: self.rm3_feedback_docs]

        if not feedback:
            return _rank_top_k(documents, initial_scores, top_k)

        expanded_weights = self._build_expanded_query(tokenized_docs, feedback, original_terms, iso3)
        final_scores = self._compute_weighted_bm25(tokenized_docs, expanded_weights)
        return _rank_top_k(documents, final_scores, top_k)

    def _build_expanded_query(
        self,
        tokenized_docs: list[list[str]],
        feedback: list[tuple[int, float]],
        original_terms: list[str],
        iso3: str | None,
    ) -> dict[str, float]:
        # RM3 relevance model: P(w|R) = sum_d P(w|d) * P(d|Q0) over the feedback set,
        # then blend its top terms with the original query terms
        # (rm3_original_query_weight vs. 1 - rm3_original_query_weight).
        score_sum = sum(s for _, s in feedback)
        function_words = (
            self._provider.get_function_words(iso3) if self._provider and iso3 else None
        )

        relevance_model: dict[str, float] = {}
        for idx, score in feedback:
            doc = tokenized_docs[idx]
            if not doc or score_sum <= 0:
                continue
            p_doc_given_query = score / score_sum
            tf: dict[str, int] = {}
            for t in doc:
                tf[t] = tf.get(t, 0) + 1
            for term, count in tf.items():
                if function_words is not None and term in function_words:
                    continue
                p_term_given_doc = count / len(doc)
                relevance_model[term] = relevance_model.get(term, 0.0) + p_term_given_doc * p_doc_given_query

        original_set = set(original_terms)
        expansion_terms = sorted(
            (item for item in relevance_model.items() if item[0] not in original_set),
            key=lambda item: item[1],
            reverse=True,
        )[: self.rm3_expansion_terms]

        expanded: dict[str, float] = {}
        orig_share = self.rm3_original_query_weight / len(original_terms)
        for term in original_terms:
            expanded[term] = expanded.get(term, 0.0) + orig_share

        expansion_sum = sum(w for _, w in expansion_terms)
        if expansion_sum > 0:
            expansion_share = 1.0 - self.rm3_original_query_weight
            for term, weight in expansion_terms:
                expanded[term] = expanded.get(term, 0.0) + expansion_share * (weight / expansion_sum)

        return expanded

    def _compute_weighted_bm25(
        self, tokenized_docs: list[list[str]], query_weights: dict[str, float]
    ) -> list[float]:
        n = len(tokenized_docs)
        scores = [0.0] * n
        if n == 0 or not query_weights:
            return scores

        term_freqs: list[dict[str, int]] = []
        for doc in tokenized_docs:
            tf: dict[str, int] = {}
            for t in doc:
                tf[t] = tf.get(t, 0) + 1
            term_freqs.append(tf)

        df: dict[str, int] = {
            term: sum(1 for tf in term_freqs if term in tf) for term in query_weights
        }

        avg_dl = sum(len(d) for d in tokenized_docs) / n if n > 0 else 1.0

        for i in range(n):
            doc_len = len(tokenized_docs[i])
            for term, q_weight in query_weights.items():
                tf_raw = term_freqs[i].get(term, 0)
                if tf_raw == 0:
                    continue
                df_val = df.get(term, 0)
                idf = math.log((n - df_val + 0.5) / (df_val + 0.5) + 1)
                tf = self.bm25_delta + tf_raw * (_K1 + 1) / (tf_raw + _K1 * (1 - _B + _B * doc_len / avg_dl))
                scores[i] += q_weight * idf * tf

        return scores


def _uniform_weights(terms: list[str]) -> dict[str, float]:
    distinct = list(dict.fromkeys(terms))
    return {t: 1.0 for t in distinct}


def _rank_top_k(documents: list[str], scores: list[float], top_k: int) -> list[RetrievalResult]:
    ranked = sorted(
        (RetrievalResult(i, documents[i], scores[i]) for i in range(len(documents)) if scores[i] > 0),
        key=lambda r: r.score,
        reverse=True,
    )
    return ranked[:top_k]
