"""G1a — 중복 후보 생성 (코드) (설계 5.3 / 00_Work_Run.md 5.1)."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ksco_qa.config import Config

SIGNALS = ("exact", "param", "same_deliverable", "tfidf_task", "card", "tfidf_orig")
SEMANTIC_SEARCH_METHOD = "task_card TF-IDF(card) + G1b added_pairs"
_PLACE_NAMES = (
    "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시",
    "울산광역시", "세종특별자치시", "경기도", "강원특별자치도", "강원도", "충청북도",
    "충청남도", "전북특별자치도", "전라북도", "전라남도", "경상북도", "경상남도",
    "제주특별자치도", "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
)
_NUMBER_RE = re.compile(r"\d+(?:[,.]\d+)*\s*(?:년|월|일|분기|주|회차|차수|회|개월|시간|분|초|%|퍼센트)?")
_HALF_YEAR_RE = re.compile(r"(?:상반기|하반기|전반기|후반기)")
_INSTITUTION_RE = re.compile(r"[가-힣]{2,12}(?:공사|공단|재단|협회|위원회|진흥원|연구원|센터)")


def _text(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value or "")).casefold()


def _remove_punctuation(value: str) -> str:
    return "".join(char for char in value if not char.isspace() and not unicodedata.category(char).startswith("P"))


def _exact_key(value: str) -> str:
    return _remove_punctuation(_text(value))


def _parameter_key(value: str) -> str:
    text = _text(value)
    for place in _PLACE_NAMES:
        text = text.replace(place.casefold(), "")
    text = _INSTITUTION_RE.sub("", text)
    text = _HALF_YEAR_RE.sub("", text)
    text = _NUMBER_RE.sub("", text)
    return _remove_punctuation(text)


def _pairs_for_equal_keys(keys: dict[int, str]) -> set[tuple[int, int]]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for row, key in keys.items():
        if key:
            grouped[key].append(row)
    pairs: set[tuple[int, int]] = set()
    for rows in grouped.values():
        ordered = sorted(rows)
        pairs.update(
            (left, right)
            for index, left in enumerate(ordered)
            for right in ordered[index + 1:]
        )
    return pairs


def effective_tasks(row_cards: list[dict[str, Any]], g0_records: list[dict[str, Any]]) -> dict[int, str]:
    """G0 KEEP은 원본 Task, REGENERATE는 재생성 Task를 후보 탐색에 사용한다."""
    records = {int(record["source_row"]): record for record in g0_records}
    tasks: dict[int, str] = {}
    for card in row_cards:
        row = int(card["source_row"])
        record = records.get(row)
        if record is None:
            continue
        action = record.get("action")
        output = record.get("output") or {}
        task = card.get("original_task") if action == "KEEP" else (
            output.get("regenerated_task_new") if action == "REGENERATE" else None
        )
        if isinstance(task, str) and task.strip():
            tasks[row] = task.strip()
    return tasks


def signal_exact(tasks: dict[int, str]) -> set[tuple[int, int]]:
    """공백·구두점 제거 후 effective_task가 동일한 쌍."""
    return _pairs_for_equal_keys({row: _exact_key(task) for row, task in tasks.items()})


def signal_param(tasks: dict[int, str]) -> set[tuple[int, int]]:
    """숫자·기간·대표 지역/기관명 제거 후 effective_task가 동일한 쌍."""
    return _pairs_for_equal_keys({row: _parameter_key(task) for row, task in tasks.items()})


def signal_same_deliverable(row_cards: list[dict[str, Any]]) -> set[tuple[int, int]]:
    """expected_filename 동일 또는 숫자를 제거한 산출물명이 같은 쌍."""
    filename_keys: dict[int, str] = {}
    title_keys: dict[int, str] = {}
    for card in row_cards:
        row = int(card["source_row"])
        filename = card.get("expected_filename")
        title = card.get("deliverable_title")
        if isinstance(filename, str) and filename.strip():
            filename_keys[row] = _text(filename).strip()
        if isinstance(title, str) and title.strip():
            title_keys[row] = _remove_punctuation(_NUMBER_RE.sub("", _text(title)))
    return _pairs_for_equal_keys(filename_keys) | _pairs_for_equal_keys(title_keys)


def _top_k_similarities(
    texts: dict[int, str], *, top_k: int, analyzer: str, ngram_range: tuple[int, int]
) -> dict[tuple[int, int], float]:
    usable = [(row, text.strip()) for row, text in sorted(texts.items()) if text.strip()]
    if len(usable) < 2:
        return {}
    rows = [row for row, _ in usable]
    try:
        matrix = TfidfVectorizer(analyzer=analyzer, ngram_range=ngram_range).fit_transform(
            [text for _, text in usable]
        )
    except ValueError as error:
        if "empty vocabulary" in str(error).lower():
            return {}
        raise
    similarities = cosine_similarity(matrix, dense_output=True)
    result: dict[tuple[int, int], float] = {}
    for index, row in enumerate(rows):
        ranked = [
            (float(similarities[index, other_index]), rows[other_index])
            for other_index in range(len(rows))
            if other_index != index
        ]
        ranked.sort(key=lambda item: (-item[0], item[1]))
        for similarity, other_row in ranked[:top_k]:
            if similarity > 0:
                pair = (min(row, other_row), max(row, other_row))
                result[pair] = max(result.get(pair, 0.0), similarity)
    return result


def signal_tfidf(texts: dict[int, str], threshold: float, top_k: int = 5) -> dict[tuple[int, int], float]:
    """문자 2~4gram TF-IDF, 행별 상위 top_k 중 임계값 이상인 쌍."""
    scores = _top_k_similarities(texts, top_k=top_k, analyzer="char", ngram_range=(2, 4))
    return {pair: score for pair, score in scores.items() if score >= threshold}


def _flatten_card(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [part for key in sorted(value) for part in _flatten_card(value[key])]
    if isinstance(value, (list, tuple)):
        return [part for item in value for part in _flatten_card(item)]
    return []


def signal_card(
    task_cards: dict[int, dict[str, Any]], threshold: float, top_k: int = 5
) -> dict[tuple[int, int], float]:
    """task_card의 토큰 1~2gram TF-IDF, 행별 상위 top_k 중 임계값 이상인 쌍."""
    texts = {row: " ".join(_flatten_card(card)) for row, card in task_cards.items()}
    scores = _top_k_similarities(texts, top_k=top_k, analyzer="word", ngram_range=(1, 2))
    return {pair: score for pair, score in scores.items() if score >= threshold}


def _candidate_pairs(
    fixed_signals: dict[str, set[tuple[int, int]]],
    adjustable_scores: dict[str, dict[tuple[int, int], float]],
    thresholds: dict[str, float],
) -> dict[tuple[int, int], dict[str, float]]:
    pairs: dict[tuple[int, int], dict[str, float]] = defaultdict(dict)
    for signal, signal_pairs in fixed_signals.items():
        for pair in signal_pairs:
            pairs[pair][signal] = 1.0
    for signal, scores in adjustable_scores.items():
        for pair, score in scores.items():
            if score >= thresholds[signal]:
                pairs[pair][signal] = score
    return pairs


def generate_candidates(
    row_cards: list[dict[str, Any]], g0_records: list[dict[str, Any]], cfg: Config
) -> dict[str, Any]:
    """여섯 신호의 합집합을 만들고, active 행×10 상한까지 가변 임계값을 단계적으로 조정한다."""
    tasks = effective_tasks(row_cards, g0_records)
    active = sorted(tasks)
    active_set = set(active)
    cards_by_row = {int(card["source_row"]): card for card in row_cards}
    g0_by_row = {int(record["source_row"]): record for record in g0_records}
    task_cards = {
        row: (g0_by_row[row].get("output") or {}).get("task_card")
        for row in active
        if isinstance((g0_by_row[row].get("output") or {}).get("task_card"), dict)
    }

    cards_missing = [row for row in active if row not in task_cards]

    fixed_signals = {
        "exact": signal_exact(tasks),
        "param": signal_param(tasks),
        "same_deliverable": signal_same_deliverable(
            [cards_by_row[row] for row in active if row in cards_by_row]
        ),
    }
    fixed_signals = {
        signal: {pair for pair in pairs if pair[0] in active_set and pair[1] in active_set}
        for signal, pairs in fixed_signals.items()
    }
    fixed_pair_count = len(set().union(*fixed_signals.values()))
    adjustable_scores = {
        "tfidf_task": _top_k_similarities(tasks, top_k=5, analyzer="char", ngram_range=(2, 4)),
        "card": _top_k_similarities(
            {row: " ".join(_flatten_card(card)) for row, card in task_cards.items()},
            top_k=5,
            analyzer="word",
            ngram_range=(1, 2),
        ),
        "tfidf_orig": _top_k_similarities(
            {row: str(cards_by_row[row].get("original_task") or "") for row in active if row in cards_by_row},
            top_k=5,
            analyzer="char",
            ngram_range=(2, 4),
        ),
    }
    thresholds = {"tfidf_task": 0.30, "card": 0.40, "tfidf_orig": 0.30}
    cap = len(active) * 10
    pairs = _candidate_pairs(fixed_signals, adjustable_scores, thresholds)
    while len(pairs) > cap and any(value < 1.0 for value in thresholds.values()):
        thresholds = {signal: min(1.0, value + 0.05) for signal, value in thresholds.items()}
        pairs = _candidate_pairs(fixed_signals, adjustable_scores, thresholds)

    signal_counts = {
        signal: sum(signal in signals for signals in pairs.values())
        for signal in SIGNALS
    }
    candidate_rows: list[dict[str, Any]] = []
    for (left, right), signals in sorted(pairs.items()):
        candidate_rows.append({
            "rows": [left, right],
            "signals": [signal for signal in SIGNALS if signal in signals],
            "similarities": {signal: round(signals[signal], 6) for signal in SIGNALS if signal in signals},
            "similarity": round(max(signals.values()), 6),
        })
    summary: dict[str, Any] = {
        "active_rows": active,
        "active_row_count": len(active),
        "search_scope": "전체 행 중 effective_task가 있는 행",
        "retrieval_methods": list(SIGNALS),
        "code_search_completed": True,
        # 00 5.1 LLM 의미 탐색 = task_card 유사도(card 신호) + G1b added_pairs (2026-10-23 결정 (a)).
        # card 신호는 task_card가 있는 행만 비교하므로 active 행 전부에 task_card가 있어야 완료.
        "semantic_search_completed": not cards_missing,
        "semantic_search_method": SEMANTIC_SEARCH_METHOD,
        "semantic_search_missing_rows": cards_missing,
        "candidate_count": len(candidate_rows),
        "mean_candidates_per_active_row": (2 * len(candidate_rows) / len(active)) if active else 0.0,
        "candidate_cap": cap,
        "cap_exceeded_by_fixed_signals": fixed_pair_count > cap,
        "signal_counts": signal_counts,
        "thresholds": thresholds,
        "target_candidates_per_row": list(cfg.G1_TARGET_CANDS),
        "pairs": candidate_rows,
    }
    canonical = json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    summary["search_id"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return summary


def make_bundles(
    pairs: list[tuple[int, int]], max_pairs: int, max_rows: int = 20
) -> list[list[tuple[int, int]]]:
    """연결 요소별로 나누고 묶음당 max_pairs·max_rows를 넘지 않게 결정적으로 자른다."""
    if max_pairs < 1 or max_rows < 2:
        raise ValueError("max_pairs는 1 이상, max_rows는 2 이상이어야 한다")
    normalized = sorted({(min(int(left), int(right)), max(int(left), int(right))) for left, right in pairs})
    if any(left == right for left, right in normalized):
        raise ValueError("후보 쌍은 서로 다른 source_row여야 한다")
    adjacency: dict[int, set[int]] = defaultdict(set)
    for left, right in normalized:
        adjacency[left].add(right)
        adjacency[right].add(left)

    components: list[set[int]] = []
    unseen = set(adjacency)
    while unseen:
        start = min(unseen)
        component = {start}
        stack = [start]
        unseen.remove(start)
        while stack:
            current = stack.pop()
            for neighbor in sorted(adjacency[current] & unseen):
                unseen.remove(neighbor)
                component.add(neighbor)
                stack.append(neighbor)
        components.append(component)

    component_for_row = {
        row: index
        for index, component in enumerate(components)
        for row in component
    }
    pairs_by_component: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for pair in normalized:
        pairs_by_component[component_for_row[pair[0]]].append(pair)

    bundles: list[list[tuple[int, int]]] = []
    for index in range(len(components)):
        component_pairs = pairs_by_component[index]
        bundle: list[tuple[int, int]] = []
        bundle_rows: set[int] = set()
        for pair in component_pairs:
            new_rows = bundle_rows | set(pair)
            if bundle and (len(bundle) >= max_pairs or len(new_rows) > max_rows):
                bundles.append(bundle)
                bundle = []
                bundle_rows = set()
            bundle.append(pair)
            bundle_rows.update(pair)
        if bundle:
            bundles.append(bundle)
    return bundles


def write_search_artifacts(result: dict[str, Any], bundles: list[list[tuple[int, int]]], run_dir: Path) -> None:
    """G1a 검색 결과·쌍·G1b 묶음을 run 폴더의 추가 전용 JSONL로 기록한다."""
    directory = Path(run_dir) / "g1"
    directory.mkdir(parents=True, exist_ok=True)
    search_id = result["search_id"]
    summary = {key: value for key, value in result.items() if key != "pairs"}
    summary["bundle_count"] = len(bundles)

    summary_path = directory / "search.jsonl"
    known_searches = set()
    if summary_path.is_file():
        for line in summary_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                known_searches.add(json.loads(line)["search_id"])
    if search_id not in known_searches:
        candidate_path = directory / "candidates.jsonl"
        known_pairs = set()
        if candidate_path.is_file():
            for line in candidate_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record = json.loads(line)
                    if record["search_id"] == search_id:
                        known_pairs.add(tuple(record["rows"]))
        missing_candidates = [
            {"search_id": search_id, **candidate}
            for candidate in result["pairs"]
            if tuple(candidate["rows"]) not in known_pairs
        ]
        with open(candidate_path, "a", encoding="utf-8", newline="\n") as stream:
            for record in missing_candidates:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")

        bundles_path = directory / "bundles.jsonl"
        known_bundle_indexes = set()
        if bundles_path.is_file():
            for line in bundles_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record = json.loads(line)
                    if record["search_id"] == search_id:
                        known_bundle_indexes.add(int(record["bundle_index"]))
        missing_bundles = [
            {"search_id": search_id, "bundle_index": index, "pairs": [list(pair) for pair in bundle]}
            for index, bundle in enumerate(bundles, start=1)
            if index not in known_bundle_indexes
        ]
        with open(bundles_path, "a", encoding="utf-8", newline="\n") as stream:
            for record in missing_bundles:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        with open(summary_path, "a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(summary, ensure_ascii=False) + "\n")
