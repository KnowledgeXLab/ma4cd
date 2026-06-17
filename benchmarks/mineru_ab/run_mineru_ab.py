#!/usr/bin/env python3
"""
Reusable A/B benchmark for MinerU integration.

Metrics:
1) Accuracy
2) Latency
3) LLM call count

Default mode is fully reproducible and offline:
- fixed fixtures
- fixed random seed
- mock LLM fallback
"""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import random
import re
import statistics
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:
    BeautifulSoup = None


LABELS = {"DATASET", "PORTAL", "ARTICLE", "GARBAGE", "UNKNOWN"}


@dataclass
class FixtureSample:
    sample_id: str
    url: str
    html: str
    expected_label: str
    description: str = ""


@dataclass
class ExtractionOutput:
    text: str
    title: str = ""
    source: str = "raw"
    used_external_mineru: bool = False
    llm_calls: int = 0


class CountingJudge:
    def __init__(self, judge_impl: "BaseJudge"):
        self.judge_impl = judge_impl
        self.calls = 0
        self.total_latency_ms = 0.0

    def judge(self, url: str, text: str, html: str) -> Tuple[str, float, str]:
        t0 = time.perf_counter()
        self.calls += 1
        label, conf, reason = self.judge_impl.judge(url, text, html)
        self.total_latency_ms += (time.perf_counter() - t0) * 1000.0
        if label not in LABELS:
            label = "UNKNOWN"
        return label, conf, reason


class BaseJudge:
    def judge(self, url: str, text: str, html: str) -> Tuple[str, float, str]:
        raise NotImplementedError


class MockJudge(BaseJudge):
    """Deterministic fallback judge for reproducible offline runs."""

    def judge(self, url: str, text: str, html: str) -> Tuple[str, float, str]:
        u = (url or "").lower()
        t = (text or "").lower()
        h = (html or "").lower()

        if any(k in u for k in ["/login", "/signin", "/register", "/cart", "/checkout"]) or \
           any(k in t for k in ["sign in", "create account", "shopping cart", "cookie policy"]):
            return "GARBAGE", 0.82, "mock_fallback: garbage signals"

        if any(k in u for k in ["/dataset", "/download", ".csv", ".json", ".xlsx", ".zip"]) or \
           any(k in t for k in ["download dataset", "data files", "api endpoint", "file format"]) or \
           any(k in h for k in [".csv", ".json", ".xlsx", ".zip"]):
            return "DATASET", 0.78, "mock_fallback: dataset signals"

        if any(k in u for k in ["/browse", "/catalog", "/collections", "/topics"]) or \
           any(k in t for k in ["browse by", "data catalog", "search datasets", "filter by"]):
            return "PORTAL", 0.76, "mock_fallback: portal signals"

        if any(k in u for k in ["doi.org", "arxiv.org", "/article", "/paper", "/publication", "/abstract"]) or \
           any(k in t for k in ["abstract", "citation", "published in", "authors"]):
            return "ARTICLE", 0.75, "mock_fallback: article signals"

        return "UNKNOWN", 0.40, "mock_fallback: no strong signal"


class RealMinerJudge(BaseJudge):
    """Optional real LLM fallback using project MinerLLMClient."""

    def __init__(self, model_name: Optional[str] = None):
        from agents.miner.llms.miner_llm import MinerLLMClient

        self.client = MinerLLMClient(model_name=model_name)

    def judge(self, url: str, text: str, html: str) -> Tuple[str, float, str]:
        system_prompt = (
            "You classify pages into one of DATASET|PORTAL|ARTICLE|GARBAGE|UNKNOWN. "
            "Return strict JSON: {label, confidence, reason}."
        )
        user_prompt = (
            f"URL: {url}\n"
            f"TEXT:\n{text[:3000]}\n"
            "Rules:\n"
            "- DATASET: downloadable structured data/API/data files\n"
            "- PORTAL: hub/catalog/search/listing page\n"
            "- ARTICLE: paper/report/publication page\n"
            "- GARBAGE: login/cart/policy/noise page\n"
            "- UNKNOWN: none of above"
        )
        obj = self.client.invoke_json(system_prompt, user_prompt, temperature=0.0)
        label = str(obj.get("label", "UNKNOWN")).upper()
        conf = float(obj.get("confidence", 0.5))
        reason = str(obj.get("reason", "real_llm_fallback"))
        if label not in LABELS:
            label = "UNKNOWN"
        return label, max(0.0, min(1.0, conf)), reason


class SmartPageClassifier:
    """Rule-first classifier + LLM fallback."""

    def __init__(self, llm_trigger_score: int = 2, ambiguity_margin: int = 1):
        self.llm_trigger_score = llm_trigger_score
        self.ambiguity_margin = ambiguity_margin

        self.dataset_signals = {
            "url_patterns": [
                r"/data(set)?s?/",
                r"/download/",
                r"/files?/",
                r"\.csv$",
                r"\.xlsx?$",
                r"\.json$",
                r"\.xml$",
                r"\.nc$",
                r"\.hdf5?$",
                r"\.zip$",
                r"\.tar\.gz$",
                r"github\.com/[^/]+/[^/]+$",
                r"github\.com/[^/]+/[^/]+/tree/",
            ],
            "url_keywords": ["dataset", "download", "github.com", "api"],
            "html_patterns": [
                r"<a[^>]*href=[\"'][^\"']*\.(csv|xlsx?|json|zip|tar\.gz)",
                r"<button[^>]*>.*?download.*?</button>",
                r"data-format=[\"']",
                r"<table[^>]*class=[\"'][^\"']*dataset",
            ],
            "text_keywords": [
                "download dataset",
                "download data",
                "access data",
                "data files",
                "file format",
                "api endpoint",
                "open data",
            ],
        }

        self.portal_signals = {
            "url_patterns": [
                r"/browse/",
                r"/catalog/",
                r"/search/",
                r"/collections?/",
                r"/categories/",
                r"/topics?/",
                r"/subjects?/",
                r"/archive(?!\.)",
            ],
            "html_patterns": [
                r"<nav[^>]*>",
                r"<ul[^>]*class=[\"'][^\"']*menu",
                r"<div[^>]*class=[\"'][^\"']*category",
                r"<form[^>]*action=[\"'][^\"']*search",
            ],
            "text_keywords": [
                "browse by",
                "search for",
                "filter by",
                "categories",
                "all datasets",
                "data catalog",
                "data portal",
            ],
        }

        self.article_signals = {
            "url_patterns": [
                r"/article/",
                r"/paper/",
                r"/publication/",
                r"/abstract/",
                r"doi\.org",
                r"arxiv\.org",
                r"/citations?/",
                r"/record/",
            ],
            "html_patterns": [
                r"<meta[^>]*name=[\"']citation_",
                r"<div[^>]*class=[\"'][^\"']*abstract",
                r"<span[^>]*class=[\"'][^\"']*author",
            ],
            "text_keywords": [
                "abstract",
                "citation",
                "references",
                "published in",
                "doi:",
                "authors:",
            ],
        }

        self.garbage_signals = {
            "url_patterns": [
                r"/login",
                r"/signin",
                r"/register",
                r"/cart",
                r"/checkout",
                r"/pricing",
                r"/subscribe",
                r"/about-us",
                r"/privacy",
                r"/terms",
                r"\.js$",
                r"\.css$",
                r"\.png$",
                r"\.jpg$",
                r"\.gif$",
            ],
            "text_keywords": [
                "sign in",
                "log in",
                "create account",
                "shopping cart",
                "add to cart",
                "buy now",
                "subscribe now",
                "cookie policy",
            ],
        }

    def classify(
        self,
        url: str,
        html: str,
        text: str,
        llm_counter: CountingJudge,
    ) -> Dict[str, Any]:
        if self._match_signals(url, html, text, self.garbage_signals) > 2:
            return {
                "label": "GARBAGE",
                "confidence": 0.95,
                "used_llm": False,
                "reason": "rule: garbage high confidence",
                "rule_score": 99.0,
            }

        scores = {
            "DATASET": self._match_signals(url, html, text, self.dataset_signals),
            "PORTAL": self._match_signals(url, html, text, self.portal_signals),
            "ARTICLE": self._match_signals(url, html, text, self.article_signals),
        }
        ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_label, top_score = ordered[0]
        second_score = ordered[1][1] if len(ordered) > 1 else -1

        if top_score >= 5:
            return {
                "label": top_label,
                "confidence": 0.95,
                "used_llm": False,
                "reason": "rule: strong",
                "rule_score": float(top_score),
            }
        if top_score >= 3:
            needs_llm = (top_score - second_score) <= self.ambiguity_margin
            if not needs_llm:
                return {
                    "label": top_label,
                    "confidence": 0.80,
                    "used_llm": False,
                    "reason": "rule: medium",
                    "rule_score": float(top_score),
                }

        if top_score < self.llm_trigger_score or (top_score - second_score) <= self.ambiguity_margin:
            llm_label, llm_conf, llm_reason = llm_counter.judge(url, text, html)
            return {
                "label": llm_label,
                "confidence": llm_conf,
                "used_llm": True,
                "reason": llm_reason,
                "rule_score": float(top_score),
            }

        return {
            "label": top_label,
            "confidence": 0.60,
            "used_llm": False,
            "reason": "rule: weak",
            "rule_score": float(top_score),
        }

    @staticmethod
    def _match_signals(url: str, html: str, text: str, signals: Dict[str, Any]) -> int:
        score = 0
        u = (url or "").lower()
        h = (html or "").lower()
        t = (text or "").lower()

        for pattern in signals.get("url_patterns", []):
            if re.search(pattern, u, re.I):
                score += 2

        for keyword in signals.get("url_keywords", []):
            if keyword in u:
                score += 1

        for pattern in signals.get("html_patterns", []):
            if h and re.search(pattern, h, re.I | re.DOTALL):
                score += 2

        for keyword in signals.get("text_keywords", []):
            if t and keyword in t:
                score += 1

        return score


class RawHtmlPerceptor:
    def extract(self, url: str, html: str) -> ExtractionOutput:
        text, title = html_to_text(html)
        return ExtractionOutput(
            text=text[:12000],
            title=title[:200],
            source="raw",
            used_external_mineru=False,
            llm_calls=0,
        )


class MinerUPerceptor:
    """
    MinerU path:
    1) try external adapter if provided
    2) fallback to local boilerplate-removal heuristic
    """

    def __init__(self, external_adapter: Optional[Callable[[str, str], Any]] = None):
        self.external_adapter = external_adapter

    def extract(self, url: str, html: str) -> ExtractionOutput:
        if self.external_adapter is not None:
            try:
                out = self.external_adapter(url, html)
                parsed = self._parse_external_result(out)
                if parsed.text.strip():
                    parsed.used_external_mineru = True
                    parsed.source = "mineru_external"
                    return parsed
            except Exception:
                pass

        clean_text, title = extract_main_like_text(html)
        return ExtractionOutput(
            text=clean_text[:12000],
            title=title[:200],
            source="mineru_heuristic",
            used_external_mineru=False,
            llm_calls=0,
        )

    @staticmethod
    def _parse_external_result(result: Any) -> ExtractionOutput:
        if isinstance(result, str):
            return ExtractionOutput(text=result, source="mineru_external", llm_calls=0)
        if isinstance(result, dict):
            llm_calls_raw = result.get("llm_calls", 0)
            try:
                llm_calls = int(llm_calls_raw)
            except Exception:
                llm_calls = 0
            return ExtractionOutput(
                text=str(result.get("text", result.get("content", ""))),
                title=str(result.get("title", "")),
                source="mineru_external",
                used_external_mineru=True,
                llm_calls=max(0, llm_calls),
            )
        return ExtractionOutput(text="", source="mineru_external", llm_calls=0)


def html_to_text(html: str) -> Tuple[str, str]:
    if not html:
        return "", ""
    if BeautifulSoup is None:
        stripped = re.sub(r"<(script|style).*?>.*?</\1>", " ", html, flags=re.I | re.S)
        stripped = re.sub(r"<[^>]+>", " ", stripped)
        stripped = re.sub(r"\s+", " ", stripped).strip()
        return stripped, ""

    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text, title


def extract_main_like_text(html: str) -> Tuple[str, str]:
    """Simple local fallback when real MinerU is unavailable."""
    if not html:
        return "", ""
    if BeautifulSoup is None:
        return html_to_text(html)

    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""

    for tag in soup(["script", "style", "noscript", "svg", "canvas", "iframe"]):
        tag.decompose()

    junk_markers = ["nav", "menu", "header", "footer", "sidebar", "cookie", "advert", "promo", "breadcrumb"]
    to_remove = []
    for tag in soup.find_all(True):
        try:
            attrs_dict = getattr(tag, "attrs", {}) or {}
            class_val = attrs_dict.get("class", [])
            class_text = " ".join(class_val) if isinstance(class_val, list) else str(class_val or "")
            attrs = " ".join(
                [
                    str(attrs_dict.get("id", "")),
                    class_text,
                    str(getattr(tag, "name", "")),
                    str(attrs_dict.get("role", "")),
                ]
            ).lower()
            if any(m in attrs for m in junk_markers):
                to_remove.append(tag)
        except Exception:
            continue

    for tag in to_remove:
        try:
            tag.decompose()
        except Exception:
            pass

    preferred = []
    for node in soup.find_all(["main", "article"]):
        txt = node.get_text(" ", strip=True)
        if len(txt) >= 120:
            preferred.append(txt)
    if preferred:
        text = " ".join(preferred)
        return re.sub(r"\s+", " ", text).strip(), title

    blocks = []
    for node in soup.find_all(["section", "div", "p", "li"]):
        txt = node.get_text(" ", strip=True)
        if len(txt) < 60:
            continue
        link_text_len = sum(len(a.get_text(" ", strip=True)) for a in node.find_all("a"))
        if txt and (link_text_len / max(1, len(txt))) > 0.6:
            continue
        blocks.append(txt)

    blocks.sort(key=len, reverse=True)
    text = " ".join(blocks[:30])
    text = re.sub(r"\s+", " ", text).strip()
    return text, title


def load_adapter(spec: Optional[str]) -> Optional[Callable[[str, str], Any]]:
    if not spec:
        return None
    if ":" not in spec:
        raise ValueError("adapter must be in format module:function")
    module_name, fn_name = spec.split(":", 1)
    mod = importlib.import_module(module_name)
    fn = getattr(mod, fn_name)
    if not callable(fn):
        raise TypeError(f"adapter target is not callable: {spec}")
    return fn


def load_fixtures(path: Path, limit: Optional[int] = None) -> List[FixtureSample]:
    if not path.exists():
        raise FileNotFoundError(f"fixtures file not found: {path}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, list):
        raise ValueError("fixtures json must be a list")
    out: List[FixtureSample] = []
    for i, item in enumerate(obj, 1):
        sample = FixtureSample(
            sample_id=str(item.get("id", f"sample_{i}")),
            url=str(item.get("url", "")),
            html=str(item.get("html", "")),
            expected_label=str(item.get("expected_label", "UNKNOWN")).upper(),
            description=str(item.get("description", "")),
        )
        if sample.expected_label not in LABELS:
            raise ValueError(f"invalid expected label in sample {sample.sample_id}: {sample.expected_label}")
        out.append(sample)
    if limit is not None:
        out = out[: max(0, limit)]
    return out


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = int(round((len(s) - 1) * p))
    return float(s[idx])


def build_judge(mode: str, real_model: Optional[str]) -> BaseJudge:
    if mode == "real":
        return RealMinerJudge(model_name=real_model)
    return MockJudge()


def run_variant(
    variant_name: str,
    samples: List[FixtureSample],
    perceptor: Any,
    runs: int,
    seed: int,
    shuffle: bool,
    judge_mode: str,
    real_model: Optional[str],
) -> Dict[str, Any]:
    classifier = SmartPageClassifier()
    all_detail_rows: List[Dict[str, Any]] = []
    run_metrics: List[Dict[str, Any]] = []

    for run_idx in range(1, runs + 1):
        ordered = list(samples)
        if shuffle:
            rnd = random.Random(seed + run_idx)
            rnd.shuffle(ordered)

        judge_counter = CountingJudge(build_judge(judge_mode, real_model))

        correct = 0
        lat_total_ms: List[float] = []
        lat_extract_ms: List[float] = []
        lat_classify_ms: List[float] = []
        extraction_llm_calls = 0

        for sample in ordered:
            t0 = time.perf_counter()
            ext = perceptor.extract(sample.url, sample.html)
            t1 = time.perf_counter()
            pred = classifier.classify(sample.url, sample.html, ext.text, judge_counter)
            t2 = time.perf_counter()
            extraction_llm_calls += max(0, int(getattr(ext, "llm_calls", 0)))

            extract_ms = (t1 - t0) * 1000.0
            classify_ms = (t2 - t1) * 1000.0
            total_ms = (t2 - t0) * 1000.0
            is_correct = pred["label"] == sample.expected_label
            if is_correct:
                correct += 1

            lat_extract_ms.append(extract_ms)
            lat_classify_ms.append(classify_ms)
            lat_total_ms.append(total_ms)

            all_detail_rows.append(
                {
                    "variant": variant_name,
                    "run_idx": run_idx,
                    "sample_id": sample.sample_id,
                    "expected_label": sample.expected_label,
                    "predicted_label": pred["label"],
                    "correct": int(is_correct),
                    "used_llm": int(pred["used_llm"]),
                    "confidence": round(float(pred["confidence"]), 4),
                    "rule_score": round(float(pred["rule_score"]), 4),
                    "extract_ms": round(extract_ms, 4),
                    "classify_ms": round(classify_ms, 4),
                    "total_ms": round(total_ms, 4),
                    "source": ext.source,
                    "used_external_mineru": int(ext.used_external_mineru),
                    "reason": pred["reason"],
                    "url": sample.url,
                    "description": sample.description,
                }
            )

        n = len(ordered)
        run_metrics.append(
            {
                "run_idx": run_idx,
                "samples": n,
                "accuracy": (correct / n) if n else 0.0,
                "llm_calls_total": judge_counter.calls + extraction_llm_calls,
                "llm_calls": judge_counter.calls,
                "llm_calls_extraction": extraction_llm_calls,
                "llm_call_rate": (judge_counter.calls / n) if n else 0.0,
                "llm_call_total_rate": ((judge_counter.calls + extraction_llm_calls) / n) if n else 0.0,
                "llm_latency_ms": judge_counter.total_latency_ms,
                "lat_total_avg_ms": statistics.mean(lat_total_ms) if lat_total_ms else 0.0,
                "lat_total_p50_ms": percentile(lat_total_ms, 0.50),
                "lat_total_p95_ms": percentile(lat_total_ms, 0.95),
                "lat_extract_avg_ms": statistics.mean(lat_extract_ms) if lat_extract_ms else 0.0,
                "lat_classify_avg_ms": statistics.mean(lat_classify_ms) if lat_classify_ms else 0.0,
            }
        )

    acc_values = [m["accuracy"] for m in run_metrics]
    avg_values = [m["lat_total_avg_ms"] for m in run_metrics]
    p95_values = [m["lat_total_p95_ms"] for m in run_metrics]
    llm_call_values = [m["llm_calls"] for m in run_metrics]
    llm_call_total_values = [m["llm_calls_total"] for m in run_metrics]
    llm_call_extraction_values = [m["llm_calls_extraction"] for m in run_metrics]
    llm_call_rate_values = [m["llm_call_rate"] for m in run_metrics]
    llm_call_total_rate_values = [m["llm_call_total_rate"] for m in run_metrics]

    summary = {
        "variant": variant_name,
        "runs": runs,
        "samples_per_run": len(samples),
        "accuracy_mean": statistics.mean(acc_values) if acc_values else 0.0,
        "accuracy_std": statistics.pstdev(acc_values) if len(acc_values) > 1 else 0.0,
        "lat_total_avg_ms_mean": statistics.mean(avg_values) if avg_values else 0.0,
        "lat_total_p95_ms_mean": statistics.mean(p95_values) if p95_values else 0.0,
        "llm_calls_total_mean": statistics.mean(llm_call_total_values) if llm_call_total_values else 0.0,
        "llm_calls_mean": statistics.mean(llm_call_values) if llm_call_values else 0.0,
        "llm_calls_extraction_mean": statistics.mean(llm_call_extraction_values) if llm_call_extraction_values else 0.0,
        "llm_call_total_rate_mean": statistics.mean(llm_call_total_rate_values) if llm_call_total_rate_values else 0.0,
        "llm_call_rate_mean": statistics.mean(llm_call_rate_values) if llm_call_rate_values else 0.0,
    }

    return {
        "summary": summary,
        "run_metrics": run_metrics,
        "details": all_detail_rows,
    }


def write_outputs(
    output_dir: Path,
    meta: Dict[str, Any],
    baseline: Dict[str, Any],
    mineru: Dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    comparison = {
        "generated_at": datetime.now().isoformat(),
        "meta": meta,
        "baseline": baseline["summary"],
        "mineru": mineru["summary"],
        "delta": {
            "accuracy_mean": mineru["summary"]["accuracy_mean"] - baseline["summary"]["accuracy_mean"],
            "lat_total_avg_ms_mean": mineru["summary"]["lat_total_avg_ms_mean"] - baseline["summary"]["lat_total_avg_ms_mean"],
            "llm_calls_total_mean": mineru["summary"]["llm_calls_total_mean"] - baseline["summary"]["llm_calls_total_mean"],
            "llm_calls_mean": mineru["summary"]["llm_calls_mean"] - baseline["summary"]["llm_calls_mean"],
            "llm_calls_extraction_mean": mineru["summary"]["llm_calls_extraction_mean"] - baseline["summary"]["llm_calls_extraction_mean"],
            "llm_call_total_rate_mean": mineru["summary"]["llm_call_total_rate_mean"] - baseline["summary"]["llm_call_total_rate_mean"],
            "llm_call_rate_mean": mineru["summary"]["llm_call_rate_mean"] - baseline["summary"]["llm_call_rate_mean"],
        },
    }

    (output_dir / "summary.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary_rows = [baseline["summary"], mineru["summary"]]
    with (output_dir / "summary.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        for row in summary_rows:
            writer.writerow(row)

    detail_rows = baseline["details"] + mineru["details"]
    if detail_rows:
        with (output_dir / "details.csv").open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(detail_rows[0].keys()))
            writer.writeheader()
            for row in detail_rows:
                writer.writerow(row)

    run_rows = []
    for row in baseline["run_metrics"]:
        item = {"variant": "baseline"}
        item.update(row)
        run_rows.append(item)
    for row in mineru["run_metrics"]:
        item = {"variant": "mineru"}
        item.update(row)
        run_rows.append(item)

    if run_rows:
        with (output_dir / "runs.csv").open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(run_rows[0].keys()))
            writer.writeheader()
            for row in run_rows:
                writer.writerow(row)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MinerU A/B benchmark (reproducible)")
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=Path("benchmarks/mineru_ab/fixtures/aerospace_pages.json"),
        help="Path to benchmark fixture JSON file",
    )
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory")
    parser.add_argument("--runs", type=int, default=5, help="Number of repeated runs")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--shuffle", action="store_true", help="Shuffle fixtures each run with seeded RNG")
    parser.add_argument("--limit", type=int, default=None, help="Use first N samples only")
    parser.add_argument(
        "--judge-mode",
        choices=["mock", "real"],
        default="mock",
        help="LLM fallback mode. mock is deterministic and offline.",
    )
    parser.add_argument("--real-model", type=str, default=None, help="Model name when judge-mode=real")
    parser.add_argument(
        "--mineru-adapter",
        type=str,
        default=None,
        help="Optional external adapter in format module:function, signature (url, html) -> dict|str",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    samples = load_fixtures(args.fixtures, limit=args.limit)

    output_dir = args.output_dir
    if output_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("reports") / f"mineru_ab_{ts}"

    adapter = load_adapter(args.mineru_adapter) if args.mineru_adapter else None
    baseline_perceptor = RawHtmlPerceptor()
    mineru_perceptor = MinerUPerceptor(external_adapter=adapter)

    meta = {
        "fixtures": str(args.fixtures),
        "runs": args.runs,
        "seed": args.seed,
        "shuffle": args.shuffle,
        "samples": len(samples),
        "judge_mode": args.judge_mode,
        "real_model": args.real_model or "",
        "mineru_adapter": args.mineru_adapter or "",
    }

    baseline = run_variant(
        variant_name="baseline_raw_html",
        samples=samples,
        perceptor=baseline_perceptor,
        runs=args.runs,
        seed=args.seed,
        shuffle=args.shuffle,
        judge_mode=args.judge_mode,
        real_model=args.real_model,
    )
    mineru = run_variant(
        variant_name="mineru_html",
        samples=samples,
        perceptor=mineru_perceptor,
        runs=args.runs,
        seed=args.seed,
        shuffle=args.shuffle,
        judge_mode=args.judge_mode,
        real_model=args.real_model,
    )

    write_outputs(output_dir, meta, baseline, mineru)

    base_s = baseline["summary"]
    mineru_s = mineru["summary"]
    print(f"[A/B] output_dir={output_dir}")
    print(
        "baseline: "
        f"acc={base_s['accuracy_mean']:.4f}, "
        f"lat_avg_ms={base_s['lat_total_avg_ms_mean']:.3f}, "
        f"llm_calls_total={base_s['llm_calls_total_mean']:.3f}"
    )
    print(
        "mineru:   "
        f"acc={mineru_s['accuracy_mean']:.4f}, "
        f"lat_avg_ms={mineru_s['lat_total_avg_ms_mean']:.3f}, "
        f"llm_calls_total={mineru_s['llm_calls_total_mean']:.3f}"
    )
    print(
        "delta:    "
        f"acc={mineru_s['accuracy_mean'] - base_s['accuracy_mean']:+.4f}, "
        f"lat_avg_ms={mineru_s['lat_total_avg_ms_mean'] - base_s['lat_total_avg_ms_mean']:+.3f}, "
        f"llm_calls_total={mineru_s['llm_calls_total_mean'] - base_s['llm_calls_total_mean']:+.3f}"
    )


if __name__ == "__main__":
    main()
