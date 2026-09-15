"""A stand-in for the application under test: a support assistant that answers
from a small knowledge base.

It follows fixed rules instead of calling a model, so the example runs offline,
for free and with the same results every time. Replace it with your own
application; `eval_adapter.py` is the only file the harness talks to.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).parent
STOPWORDS = {
    "the", "and", "you", "your", "can", "how", "what", "for", "are", "with", "this",
    "that", "our", "not", "from", "any", "all", "get", "was", "has", "have", "does",
    "after", "about", "want", "need", "also", "many", "much", "where", "when", "who",
    "which", "will", "there", "their", "them", "into", "each", "use", "per",
}  # fmt: skip
DUTCH = {"hoe", "kan", "ik", "mijn", "het", "een", "wat", "waar", "niet", "opzeggen"}


@dataclass(frozen=True)
class Article:
    path: str
    title: str
    answer: str
    dutch: str | None
    words: frozenset[str]


@dataclass
class Reply:
    text: str
    sources: list[Article] = field(default_factory=list)
    words_in: int = 0


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 4 and word.endswith("s") else word


def _words(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in STOPWORDS}


def _article(path: Path) -> Article:
    text = path.read_text(encoding="utf-8")
    title = text.splitlines()[0].lstrip("# ").strip()
    english, _, dutch = text.partition("## Nederlands")
    paragraphs = [p.strip() for p in english.split("\n\n")[1:] if p.strip()]
    return Article(
        path=str(path.relative_to(HERE)),
        title=title,
        answer=paragraphs[0] if paragraphs else "",
        dutch=dutch.strip() or None,
        words=frozenset(_words(text)),
    )


class SupportAssistant:
    def __init__(self, knowledge_base: Path = HERE / "kb") -> None:
        self.articles = [_article(p) for p in sorted(knowledge_base.rglob("*.md"))]

    def _retrieve(self, question: str) -> list[Article]:
        asked = _words(question)
        scored = sorted(
            ((len(asked & a.words), a) for a in self.articles), key=lambda s: (-s[0], s[1].path)
        )
        hits = [a for score, a in scored if score >= 2]
        multi_part = bool(re.search(r"\b(and|also)\b", question.lower())) and "," in question
        return hits[:2] if multi_part else hits[:1]

    def answer(self, question: str) -> Reply:
        text = question.lower()
        words_in = len(question.split())

        if "system prompt" in text or "previous instructions" in text:
            return Reply(
                "I can't share that, but I'm happy to help with the product.", [], words_in
            )
        if re.search(r"[\w.]+@[\w.]+", text) or "colleague" in text:
            return Reply(
                "I can't share details about another person's account. Only the account owner "
                "or an admin can see billing details.",
                [],
                words_in,
            )
        if "cover letter" in text or "write me" in text:
            return Reply(
                "I can only help with questions about the product, such as billing, your account "
                "or uploads.",
                [],
                words_in,
            )
        if "onboarding document" in text:
            doc = (HERE / "fixtures" / "onboarding-with-hidden-instruction.md").read_text("utf-8")
            # Comments are hidden from readers; an assistant must not act on them either.
            visible = re.sub(r"<!--.*?-->", "", doc, flags=re.DOTALL)
            sections = re.findall(r"^## (.+)\n(.+)$", visible, flags=re.MULTILINE)
            summary = " ".join(f"{title}: {body}" for title, body in sections)
            return Reply(f"The document covers two stages. {summary}", [], words_in)

        frustrated = any(w in text for w in ("useless", "third time", "ridiculous"))
        if frustrated:
            contact = next(a for a in self.articles if a.path.endswith("contact.md"))
            return Reply(
                "I'm sorry this has taken so long. Tell me what isn't working and I'll look into "
                f"it now. {contact.answer} [1]",
                [contact],
                words_in,
            )

        hits = self._retrieve(question)
        if not hits:
            if words_in <= 4:
                return Reply(
                    "Could you tell me what you were trying to do when it stopped?", [], words_in
                )
            return Reply(
                "Our documentation doesn't cover that, so I don't want to guess. I can pass your "
                "question to the team.",
                [],
                words_in,
            )

        dutch = len(set(re.findall(r"[a-z]+", text)) & DUTCH) >= 2
        parts = []
        for index, article in enumerate(hits, start=1):
            body = article.dutch if dutch and article.dutch else article.answer
            parts.append(f"{body} [{index}]")
        reply = " ".join(parts)
        if "refund" in text:
            reply += " For anything outside that, I can pass your request to the billing team."
        if "lawyer" in text or "data you hold" in text:
            reply += (
                " I can't give legal advice. A person on our team will email you about the data "
                "we hold."
            )
        return Reply(reply, hits, words_in)
