"""App Finder: says which apps can do a job, and lists the apps there are.

The list of apps is `apps.json`, beside this file, copied by hand from the
Apps page on the day in its `taken` field. An app is told nothing about who is
asking and cannot sign in, so it cannot read the live catalogue; the list goes
out of date whenever an app is added or changed, and each answer says how old
it is.

Matching is deliberately plain: the words of the job are cut down to rough
stems and compared with each app's name, its hand-written keywords and the
first sentence of its summary, in that order of weight.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pippa_agentapp_sdk import (
    AgentAppError,
    Call,
    Manifest,
    Result,
    load_manifest_file,
    validate_manifest,
)

MANIFEST_PATH = Path(__file__).with_name("manifest.yaml")
CATALOGUE = json.loads(Path(__file__).with_name("apps.json").read_text("utf-8"))

#: How many apps a search returns at most.
MAX_RESULTS = 3

#: A match needs at least this score: one keyword, or one word of a name. A
#: single word shared with a summary is a coincidence, not a match.
MIN_SCORE = 2

NAME_WEIGHT, KEYWORD_WEIGHT, SUMMARY_WEIGHT = 3, 2, 1

#: Words that say nothing about which app is wanted: ordinary words, and the
#: words every summary and every question about apps uses.
IGNORED = frozenset("""
a an the my me i im is are was were be been do does did have has had of on in
at to for with and or but if it its this that these those so just please can
could would will from into by as any some what whats which who where when why
how much many long there you your app apps work works out say says tell find
finds help get know want need use something thing anything way named name
nothing anywhere send sent time
""".split())

_WORD = re.compile(r"[a-z0-9]+")


class NoTask(AgentAppError):
    user_message = (
        "Tell me what you want an app to do, for example \"convert pounds to "
        "euros\", or ask what apps there are."
    )
    retryable = False


class UnknownAuthor(AgentAppError):
    user_message = "I do not know an author with that name."
    retryable = False


def _stem(word: str) -> str:
    """Cut a word down far enough that "converts" and "converter" meet."""
    for suffix in ("ing", "ers", "er", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    if len(word) > 3 and word[-1] == word[-2] and word[-1] not in "aeiou":
        word = word[:-1]            # splitting -> splitt -> split
    if len(word) > 3 and word.endswith("e"):
        word = word[:-1]            # scale, scaler, scaling -> scal
    return word


def _stems(text: str) -> set[str]:
    words = (w for w in _WORD.findall(text.lower()) if w not in IGNORED)
    return {s for s in map(_stem, words) if s not in IGNORED}


def _first_sentence(text: str) -> str:
    return text.split(". ")[0].rstrip(".") + "."


def _label(entry: dict) -> str:
    return f"{entry['name']}, from {entry['author']}"


class App:
    def __init__(self) -> None:
        self._manifest = validate_manifest(load_manifest_file(MANIFEST_PATH))

    @property
    def manifest(self) -> Manifest:
        return self._manifest

    def handle(self, call: Call) -> Result:
        if call.outcome_id == "apps.find":
            return self._find((call.inputs.get("task") or "").strip())
        if call.outcome_id == "apps.list":
            return self._list((call.inputs.get("author") or "").strip())
        raise AgentAppError(f"this app cannot do {call.outcome_id!r}")

    def _find(self, task: str) -> Result:
        wanted = _stems(task)
        if not wanted:
            raise NoTask(f"no job in {task!r}")

        scored = [(self._score(entry, wanted), entry) for entry in CATALOGUE["apps"]]
        matches = sorted(
            ((score, entry) for score, entry in scored if score >= MIN_SCORE),
            key=lambda pair: (-pair[0], pair[1]["name"]),
        )[:MAX_RESULTS]

        data = {
            "matched": len(matches),
            "apps": [
                f"{_label(entry)}: {_first_sentence(entry['summary'])}"
                for _, entry in matches
            ],
            "catalogue_size": len(CATALOGUE["apps"]),
            "catalogue_date": CATALOGUE["taken"],
        }
        # Only a clear winner is named as the best match; a tie is not one.
        if len(matches) == 1 or (matches and matches[0][0] > matches[1][0]):
            data["best_match"] = matches[0][1]["name"]

        return Result(data=data, narrative=self._find_sentence(matches, data))

    @staticmethod
    def _score(entry: dict, wanted: set[str]) -> int:
        name = _stems(entry["name"])
        keywords = _stems(" ".join(entry["keywords"]))
        summary = _stems(_first_sentence(entry["summary"]))
        score = 0
        for stem in wanted:
            if stem in name:
                score += NAME_WEIGHT
            elif stem in keywords:
                score += KEYWORD_WEIGHT
            elif stem in summary:
                score += SUMMARY_WEIGHT
        return score

    @staticmethod
    def _find_sentence(matches: list, data: dict) -> str:
        if not matches:
            return (
                f"None of the {data['catalogue_size']} apps in the list taken "
                f"on {data['catalogue_date']} looks able to do that."
            )
        names = [entry["name"] for _, entry in matches]
        if "best_match" in data:
            return f"{data['best_match']} looks like the app for that."
        if len(names) == 2:
            return f"{names[0]} and {names[1]} could both help."
        return f"{', '.join(names[:-1])} and {names[-1]} could all help."

    def _list(self, author: str) -> Result:
        entries = CATALOGUE["apps"]
        if author:
            entries = [e for e in entries if e["author"].lower() == author.lower()]
            if not entries:
                error = UnknownAuthor(f"no apps from {author!r}")
                authors = sorted({e["author"] for e in CATALOGUE["apps"]})
                error.user_message = (
                    f"I do not know an author called {author}. The authors I "
                    f"know are {', '.join(authors)}."
                )
                raise error

        labels = sorted(_label(e) for e in entries)
        who = f" from {entries[0]['author']}" if author else ""
        return Result(
            data={
                "count": len(labels),
                "apps": labels,
                "catalogue_date": CATALOGUE["taken"],
            },
            narrative=(
                f"There are {len(labels)} apps{who} in the list taken on "
                f"{CATALOGUE['taken']}."
            ),
        )
