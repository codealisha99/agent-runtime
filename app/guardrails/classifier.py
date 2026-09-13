"""Trained multinomial Naive Bayes prompt-injection classifier."""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).with_name("injection_data.json")
_TOKEN = re.compile(r"[a-z']+")


def tokenize(text: str) -> list[str]:
    low = text.lower()
    words = _TOKEN.findall(low)
    grams = [low[i : i + 4] for i in range(max(0, len(low) - 3))]
    return words + grams


class InjectionClassifier:
    def __init__(self) -> None:
        self.log_prior = [0.0, 0.0]
        self.log_prob: list[dict[str, float]] = [{}, {}]
        self.vocab = 0
        self.ready = False

    def fit(self, texts: list[str], labels: list[int]) -> None:
        counts: list[dict[str, int]] = [{}, {}]
        totals = [0, 0]
        docs = [0, 0]
        vocab: set[str] = set()
        for text, label in zip(texts, labels):
            docs[label] += 1
            for token in tokenize(text):
                counts[label][token] = counts[label].get(token, 0) + 1
                totals[label] += 1
                vocab.add(token)
        n = max(1, sum(docs))
        self.vocab = max(1, len(vocab))
        self.log_prior = [math.log((docs[i] + 1) / (n + 2)) for i in range(2)]
        self.log_prob = [{}, {}]
        for label in (0, 1):
            denom = totals[label] + self.vocab
            for token in vocab:
                self.log_prob[label][token] = math.log((counts[label].get(token, 0) + 1) / denom)
        self.ready = True

    def score(self, text: str) -> float:
        if not self.ready:
            return 0.0
        log_scores = list(self.log_prior)
        unseen = math.log(1 / (self.vocab + 1))
        for token in tokenize(text):
            for label in (0, 1):
                log_scores[label] += self.log_prob[label].get(token, unseen)
        m = max(log_scores)
        exp0 = math.exp(log_scores[0] - m)
        exp1 = math.exp(log_scores[1] - m)
        return exp1 / (exp0 + exp1)


@lru_cache(maxsize=1)
def get_classifier() -> InjectionClassifier:
    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    texts = list(raw["benign"]) + list(raw["injection"])
    labels = [0] * len(raw["benign"]) + [1] * len(raw["injection"])
    model = InjectionClassifier()
    model.fit(texts, labels)
    return model
