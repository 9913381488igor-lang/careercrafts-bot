"""
Источники вакансий для бота careercrafts.

1. «Работа России» (opendata.trudvsem.ru) — бесплатно, без ключа.
2. hh.ru — только если в переменных окружения задан HH_TOKEN
   (токен приложения с dev.hh.ru). Без токена hh.ru отвечает 403 forbidden.

fetch() возвращает (jobs, error): если все источники упали — error не пустой,
и бот честно пишет об этом пользователю, а не «вакансий нет».
"""

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Поисковые фразы по категориям (для «Работы России» каждая фраза — отдельный запрос)
CATEGORY_QUERIES = {
    "Разработка / IT":       ["программист удаленно", "разработчик удаленно", "тестировщик удаленно",
                              "специалист технической поддержки удаленно"],
    "Маркетинг / SMM":       ["маркетолог удаленно", "SMM удаленно", "таргетолог", "контент-менеджер удаленно"],
    "Дизайн":                ["дизайнер удаленно", "графический дизайнер", "веб-дизайнер"],
    "Продажи / менеджмент":  ["менеджер по продажам удаленно", "менеджер удаленно", "оператор продаж удаленно"],
    "Копирайтинг / контент": ["копирайтер", "контент-менеджер удаленно", "редактор удаленно"],
    "Бухгалтерия / финансы": ["бухгалтер удаленно", "экономист удаленно", "финансист удаленно"],
    "HR / рекрутинг":        ["рекрутер удаленно", "менеджер по персоналу удаленно", "HR удаленно"],
    "Другое":                ["удаленно", "дистанционная работа", "оператор удаленно", "специалист удаленно"],
}

# Для hh.ru — одна фраза на категорию (поиск hh сам понимает синонимы)
HH_QUERIES = {
    "Разработка / IT":       "программист OR разработчик OR тестировщик",
    "Маркетинг / SMM":       "маркетолог OR SMM OR таргетолог",
    "Дизайн":                "дизайнер",
    "Продажи / менеджмент":  "менеджер по продажам OR менеджер",
    "Копирайтинг / контент": "копирайтер OR контент-менеджер OR редактор",
    "Бухгалтерия / финансы": "бухгалтер OR экономист OR финансист",
    "HR / рекрутинг":        "рекрутер OR HR OR менеджер по персоналу",
    "Другое":                "",
}

SALARY_VALUES = {
    "Любая зарплата": None,
    "от 30 000 ₽":    30000,
    "от 50 000 ₽":    50000,
    "от 80 000 ₽":    80000,
    "от 120 000 ₽":   120000,
    "от 200 000 ₽":   200000,
}

REMOTE_RE = re.compile(r"удал|дистанц", re.I)

# --- фильтр подозрительных вакансий (те же принципы, что в ежедневном посте) ---
SCAM_RE = re.compile(
    r"вложени|предоплат|оплат\S* (за )?обучени|платн\S* обучени|взнос|депозит|(?<![а-яё])крипт|"
    r"инвестиц|ставк\S* на спорт|пассивн\S* доход|л[её]гк\S* (заработ|деньг)|от имени девуш|"
    r"переписк\S* с мужч|сетев\S* маркетинг|\bmlm\b|выкуп\S* товар|отзыв\S* (на|для) маркетплейс|"
    r"ставить (лайк|оценк)|наборщик|набор текст|перепечат|без вложений|выплаты? каждый день|"
    r"ежедневн\S* выплат", re.I)
IP_RE = re.compile(r"^(ИП|ИНДИВИДУАЛЬН\S* ПРЕДПРИНИМ\S*)(\s|$)", re.I)
SIMPLE_ROLE_RE = re.compile(
    r"оператор|ввод\S* данных|модератор|ассистент|помощник|чат|администратор(?! веб| сайт| систем)|"
    r"риел?тор|менеджер по работе с клиентами|диспетчер|курьер|подбор", re.I)
REPOST_RE = re.compile(r"^\s*Вакансия компании:", re.I)


def _desc_key(job: dict) -> str:
    return re.sub(r"[^а-яёa-z]", "", (job.get("description") or "").lower())[:150]


def filter_suspicious(jobs: list) -> list:
    """Убрать подозрительные вакансии. Если у работодателя нашлась хоть одна
    подозрительная — убираем все его вакансии."""
    bad_companies, flagged = set(), set()
    for j in jobs:
        text = f"{j['title']} {j.get('description', '')}"
        company = j.get("company", "")
        lo = j.get("salary_min") or 0
        hi = max(lo, j.get("salary_max") or 0)
        is_ip = bool(IP_RE.search(company))
        reason = None
        if SCAM_RE.search(text):
            reason = "схема/оплата/крипта"
        elif is_ip and REPOST_RE.search(j.get("description", "")):
            reason = "ИП публикует вакансии чужих компаний"
        elif is_ip and SIMPLE_ROLE_RE.search(j["title"]) and hi >= 70000:
            reason = "ИП, простая работа, зарплата выше рынка"
        elif lo >= 150000 and j.get("experience", 0) == 0:
            reason = "нереальная зарплата без опыта"
        elif lo and hi >= 200000 and hi >= 3 * lo:
            reason = "вилка «до 350 000» — оплата только с продаж"
        if reason:
            flagged.add(j["id"])
            if company:
                bad_companies.add(company)
            logger.info(f"filtered: {j['title']} / {company} — {reason}")

    # массовые объявления: один работодатель, один текст, 3+ разных названия
    groups = {}
    for j in jobs:
        if REPOST_RE.search(j.get("description", "")):
            continue
        groups.setdefault((j.get("company", ""), _desc_key(j)), set()).add(j["title"])
    for (company, _), titles in groups.items():
        if len(titles) >= 3 and company:
            bad_companies.add(company)
            logger.info(f"filtered company (mass ads): {company}")

    out, seen = [], set()
    for j in jobs:
        if j["id"] in flagged or j.get("company", "") in bad_companies:
            continue
        k = _desc_key(j)
        if k and k in seen:          # одинаковый текст — показываем один раз
            continue
        seen.add(k)
        out.append(j)
    return out

MAX_AGE_DAYS = 45          # старше — не показываем
CACHE_TTL = 30 * 60        # кэш результатов по категории, сек


class JobsFetcher:
    TRUD_API = "https://opendata.trudvsem.ru/api/v1/vacancies"
    HH_API = "https://api.hh.ru/vacancies"

    def __init__(self):
        self.hh_token = os.environ.get("HH_TOKEN", "").strip()
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "careercrafts-tg-bot/1.1 (t.me/careercrafts)"
        self._cache = {}   # category -> (timestamp, jobs)

    # ------------------------------------------------------------------ public
    def fetch(self, category: str, salary: str, per_page: int = 10):
        """Вернуть (список вакансий, текст ошибки или None)."""
        sal_min = SALARY_VALUES.get(salary)
        jobs, errors = self._pool(category)
        if sal_min:
            jobs = [j for j in jobs if (j["salary_max"] or j["salary_min"] or 0) >= sal_min]
        error = None
        if not jobs and errors:
            error = "; ".join(errors)
        return jobs[:per_page], error

    # ----------------------------------------------------------------- private
    def _pool(self, category: str):
        cached = self._cache.get(category)
        if cached and time.time() - cached[0] < CACHE_TTL:
            return cached[1], []

        jobs, errors = [], []
        if self.hh_token:
            try:
                jobs += self._fetch_hh(category)
            except Exception as e:
                logger.error(f"hh.ru error: {e}")
                errors.append(f"hh.ru: {e}")
        try:
            jobs += self._fetch_trud(category)
        except Exception as e:
            logger.error(f"trudvsem error: {e}")
            errors.append(f"Работа России: {e}")

        # дубли и сортировка: свежие сверху
        seen, uniq = set(), []
        for j in jobs:
            key = (j["title"].lower(), j["company"].lower())
            if j["id"] in seen or key in seen:
                continue
            seen.update({j["id"], key})
            uniq.append(j)
        uniq.sort(key=lambda j: j["date"], reverse=True)
        before = len(uniq)
        uniq = filter_suspicious(uniq)
        logger.info(f"suspicious filter: {before} -> {len(uniq)}")

        if uniq:   # пустой результат не кэшируем — вдруг временный сбой
            self._cache[category] = (time.time(), uniq)
        logger.info(f"pool[{category}]: {len(uniq)} jobs, errors={errors}")
        return uniq, errors

    def _fetch_trud(self, category: str) -> list:
        queries = CATEGORY_QUERIES.get(category, CATEGORY_QUERIES["Другое"])
        cutoff = (date.today() - timedelta(days=MAX_AGE_DAYS)).isoformat()
        def one(q):
            r = self.session.get(self.TRUD_API, params={"text": q, "limit": 100, "offset": 0}, timeout=30)
            r.raise_for_status()
            return (r.json().get("results") or {}).get("vacancies") or []

        out, ok, last_err = [], 0, None
        with ThreadPoolExecutor(max_workers=len(queries)) as pool:
            futures = {q: pool.submit(one, q) for q in queries}
        for q, fut in futures.items():
            try:
                items = fut.result()
                ok += 1
            except Exception as e:
                last_err = e
                logger.warning(f"trudvsem query '{q}' failed: {e}")
                continue
            for item in items:
                v = item.get("vacancy") or {}
                if not REMOTE_RE.search(v.get("employment") or ""):
                    continue
                if (v.get("creation-date") or "") < cutoff:
                    continue
                out.append(self._parse_trud(v))
        if ok == 0 and last_err:
            raise last_err
        return out

    def _fetch_hh(self, category: str) -> list:
        params = {
            "text": HH_QUERIES.get(category, ""), "area": 113, "work_format": "REMOTE",
            "schedule": "remote", "per_page": 50, "order_by": "publication_time",
            "currency": "RUR", "period": MAX_AGE_DAYS,
        }
        headers = {"Authorization": f"Bearer {self.hh_token}",
                   "HH-User-Agent": "careercrafts-tg-bot/1.1 (t.me/careercrafts)"}
        r = self.session.get(self.HH_API, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        return [self._parse_hh(i) for i in r.json().get("items", [])]

    # ----------------------------------------------------------------- parsing
    def _parse_trud(self, v: dict) -> dict:
        lo = v.get("salary_min") or None
        hi = v.get("salary_max") or None
        duty = re.sub(r"<[^>]+>", " ", v.get("duty") or "")
        duty = re.sub(r"\s+", " ", duty).strip()
        return {
            "id":          f"trud_{v.get('id')}",
            "title":       v.get("job-name", "Вакансия"),
            "company":     (v.get("company") or {}).get("name", ""),
            "salary":      self._fmt(lo, hi, "₽"),
            "salary_min":  lo, "salary_max": hi,
            "format":      "Удалёнка",
            "description": duty,
            "url":         v.get("vac_url", "https://trudvsem.ru"),
            "date":        v.get("creation-date", ""),
            "source":      "Работа России",
            "experience":  (v.get("requirement") or {}).get("experience") or 0,
        }

    def _parse_hh(self, item: dict) -> dict:
        s = item.get("salary") or {}
        cur = "₽" if s.get("currency", "RUR") == "RUR" else s.get("currency", "")
        snippet = item.get("snippet") or {}
        desc = " ".join(filter(None, [snippet.get("responsibility"), snippet.get("requirement")]))
        desc = re.sub(r"<[^>]+>", "", desc)
        return {
            "id":          f"hh_{item['id']}",
            "title":       item["name"],
            "company":     (item.get("employer") or {}).get("name", ""),
            "salary":      self._fmt(s.get("from"), s.get("to"), cur),
            "salary_min":  s.get("from"), "salary_max": s.get("to"),
            "format":      "Удалёнка",
            "description": desc,
            "url":         item["alternate_url"],
            "date":        (item.get("published_at") or "")[:10],
            "source":      "hh.ru",
        }

    @staticmethod
    def _fmt(lo: Optional[int], hi: Optional[int], cur: str) -> str:
        f = lambda x: f"{int(x):,}".replace(",", " ")
        if lo and hi and lo != hi:
            return f"{f(lo)} – {f(hi)} {cur}"
        if lo:
            return f"от {f(lo)} {cur}"
        if hi:
            return f"до {f(hi)} {cur}"
        return "не указана"
