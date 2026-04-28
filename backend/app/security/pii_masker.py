"""PII masking with optional Presidio support and deterministic fallback."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from app.config import settings

try:  # pragma: no cover - optional dependency
    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
    from presidio_analyzer.nlp_engine import NlpArtifacts, NlpEngine
except ImportError:  # pragma: no cover - optional dependency
    AnalyzerEngine = None
    NlpArtifacts = None
    NlpEngine = object
    Pattern = None
    PatternRecognizer = None
    RecognizerRegistry = None


@dataclass(frozen=True)
class Detection:
    start: int
    end: int
    label: str
    value: str


class _NoOpNlpEngine(NlpEngine):  # pragma: no cover - thin compatibility shim
    def load(self) -> None:
        return None

    def is_loaded(self) -> bool:
        return True

    def process_text(self, text: str, language: str):
        return NlpArtifacts(
            entities=[],
            tokens=[],
            tokens_indices=[],
            lemmas=[],
            nlp_engine=self,
            language=language,
        )

    def process_batch(self, texts, language: str, **kwargs):
        for text in texts:
            yield text, self.process_text(text, language)

    def is_stopword(self, word: str, language: str) -> bool:
        return False

    def is_punct(self, word: str, language: str) -> bool:
        return False

    def get_supported_entities(self) -> list[str]:
        return []

    def get_supported_languages(self) -> list[str]:
        return ["zh"]


class PIIMasker:
    """Mask common Chinese PII with optional Presidio recognizers."""

    _presidio_init_attempted = False
    _presidio_analyzer = None

    PHONE_RE = re.compile(r"(?<!\d)(1\d{10})(?!\d)")
    ID_RE = re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)")
    MONEY_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?(?:元|万元|w|W))(?!\w)")
    EMAIL_RE = re.compile(r"\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
    BANK_RE = re.compile(r"(?<!\d)(\d{12,19})(?!\d)")
    ADDRESS_RE = re.compile(
        r"((?:地址|住址|联系地址|办公地址)[:：]?\s*[^\n，。；;]{4,60}(?:省|市|区|县|路|街|号|楼|室)[^\n，。；;]{0,40})"
    )
    NAME_RE = re.compile(r"((?:姓名|联系人|申请人|员工|负责人)[:：]?\s*[\u4e00-\u9fff]{2,4})")

    def __init__(self):
        self.enabled = settings.pii_masking_enabled
        self._recognizers = self._build_presidio_recognizers() if settings.pii_presidio_enabled else []

    def mask(self, text: str) -> tuple[str, dict[str, str]]:
        if not self.enabled or not text:
            return text, {}

        detections = self._detect_with_presidio(text) or self._detect_locally(text)
        if not detections:
            return text, {}

        mapping: dict[str, str] = {}
        counters: dict[str, int] = {}
        masked_text = text

        for item in sorted(detections, key=lambda current: (current.start, current.end), reverse=True):
            counters[item.label] = counters.get(item.label, 0) + 1
            placeholder = f"[{item.label}_{counters[item.label]}]"
            mapping[placeholder] = item.value
            masked_text = masked_text[: item.start] + placeholder + masked_text[item.end :]

        return masked_text, mapping

    def restore(self, masked_text: str, mapping: dict[str, str]) -> str:
        restored = masked_text
        for placeholder, original in mapping.items():
            restored = restored.replace(placeholder, original)
        return restored

    def _detect_with_presidio(self, text: str) -> list[Detection]:
        analyzer = self._get_presidio_analyzer()
        if analyzer is None:
            return []
        try:
            results = analyzer.analyze(
                text=text,
                language="zh",
                entities=[label for label, _recognizer in self._recognizers],
            )
        except (AttributeError, TypeError, ValueError, RuntimeError, KeyError):
            return []

        detections: list[Detection] = []
        for item in results:
            value = text[int(item.start) : int(item.end)]
            if not value.strip():
                continue
            detections.append(
                Detection(
                    start=int(item.start),
                    end=int(item.end),
                    label=str(item.entity_type),
                    value=value,
                )
            )
        return self._dedupe_overlaps(detections)

    def _get_presidio_analyzer(self):
        if not settings.pii_presidio_enabled or not self._recognizers:
            return None
        if self.__class__._presidio_analyzer is not None:
            return self.__class__._presidio_analyzer
        if self.__class__._presidio_init_attempted:
            return None
        self.__class__._presidio_init_attempted = True
        if AnalyzerEngine is None or RecognizerRegistry is None or NlpArtifacts is None:
            return None
        try:
            registry = RecognizerRegistry(
                recognizers=[recognizer for _label, recognizer in self._recognizers],
                supported_languages=["zh"],
            )
            self.__class__._presidio_analyzer = AnalyzerEngine(
                registry=registry,
                nlp_engine=_NoOpNlpEngine(),
                supported_languages=["zh"],
            )
        except (AttributeError, ImportError, OSError, RuntimeError, TypeError, ValueError):
            self.__class__._presidio_analyzer = None
        return self.__class__._presidio_analyzer

    def _detect_locally(self, text: str) -> list[Detection]:
        detections: list[Detection] = []
        patterns: Iterable[tuple[str, re.Pattern[str]]] = (
            ("PHONE", self.PHONE_RE),
            ("ID", self.ID_RE),
            ("MONEY", self.MONEY_RE),
            ("EMAIL", self.EMAIL_RE),
            ("BANK", self.BANK_RE),
            ("ADDRESS", self.ADDRESS_RE),
            ("NAME", self.NAME_RE),
        )
        for label, pattern in patterns:
            for match in pattern.finditer(text):
                value = match.group(1)
                if label == "BANK" and self._looks_like_phone_or_id(value):
                    continue
                detections.append(
                    Detection(
                        start=match.start(1),
                        end=match.end(1),
                        label=label,
                        value=value,
                    )
                )
        return self._dedupe_overlaps(detections)

    def _build_presidio_recognizers(self):  # pragma: no cover - optional dependency path
        if Pattern is None or PatternRecognizer is None:
            return []
        try:
            return [
                (
                    "PHONE",
                    PatternRecognizer(
                        supported_entity="PHONE",
                        patterns=[Pattern(name="cn_phone", regex=r"1\d{10}", score=0.8)],
                        supported_language="zh",
                    ),
                ),
                (
                    "ID",
                    PatternRecognizer(
                        supported_entity="ID",
                        patterns=[Pattern(name="cn_id", regex=r"\d{17}[\dXx]", score=0.85)],
                        supported_language="zh",
                    ),
                ),
                (
                    "MONEY",
                    PatternRecognizer(
                        supported_entity="MONEY",
                        patterns=[Pattern(name="money", regex=r"\d+(?:\.\d+)?(?:元|万元|w|W)", score=0.65)],
                        supported_language="zh",
                    ),
                ),
                (
                    "EMAIL",
                    PatternRecognizer(
                        supported_entity="EMAIL",
                        patterns=[Pattern(name="email", regex=self.EMAIL_RE.pattern, score=0.9)],
                        supported_language="zh",
                    ),
                ),
                (
                    "BANK",
                    PatternRecognizer(
                        supported_entity="BANK",
                        patterns=[Pattern(name="bank_account", regex=r"\d{12,19}", score=0.7)],
                        supported_language="zh",
                    ),
                ),
                (
                    "ADDRESS",
                    PatternRecognizer(
                        supported_entity="ADDRESS",
                        patterns=[Pattern(name="address", regex=self.ADDRESS_RE.pattern, score=0.6)],
                        supported_language="zh",
                    ),
                ),
                (
                    "NAME",
                    PatternRecognizer(
                        supported_entity="NAME",
                        patterns=[Pattern(name="labeled_name", regex=self.NAME_RE.pattern, score=0.55)],
                        supported_language="zh",
                    ),
                ),
            ]
        except (AttributeError, ImportError, OSError, RuntimeError, TypeError, ValueError):
            return []

    def _dedupe_overlaps(self, detections: list[Detection]) -> list[Detection]:
        ordered = sorted(
            detections,
            key=lambda item: (item.start, -(item.end - item.start), item.label),
        )
        kept: list[Detection] = []
        for item in ordered:
            if any(not (item.end <= existing.start or item.start >= existing.end) for existing in kept):
                continue
            kept.append(item)
        return kept

    def _looks_like_phone_or_id(self, value: str) -> bool:
        return bool(self.PHONE_RE.fullmatch(value) or self.ID_RE.fullmatch(value))
