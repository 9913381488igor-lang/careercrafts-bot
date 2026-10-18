import requests
import logging
from typing import Optional

logger = logging.getLogger(__name__)

CATEGORY_QUERIES = {
    "Разработка / IT":        "программист разработчик удалённо",
    "Маркетинг / SMM":        "маркетолог SMM менеджер удалённо",
    "Дизайн":                 "дизайнер UI UX удалённо",
    "Продажи / менеджмент":   "менеджер продажи удалённо",
    "Копирайтинг / контент":  "копирайтер контент-менеджер удалённо",
    "Бухгалтерия / финансы":  "бухгалтер финансист удалённо",
    "HR / рекрутинг":         "HR рекрутер удалённо",
    "Другое":                 "удалённая работа",
}

SALARY_VALUES = {
    "Любая зарплата":  None,
    "от 30 000 ₽":    30000,
    "от 50 000 ₽":    50000,
    "от 80 000 ₽":    80000,
    "от 120 000 ₽":   120000,
    "от 200 000 ₽":   200000,
}


class JobsFetcher:
    HH_API = "https://api.hh.ru/vacancies"
    HEADERS = {"User-Agent": "careercrafts-tg-bot/1.0"}

    def fetch(self, category: str, salary: str, per_page: int = 10) -> list:
        query   = CATEGORY_QUERIES.get(category, "удалённая работа")
        sal_min = SALARY_VALUES.get(salary)
        params  = {
            "text": query, "area": 113, "schedule": "remote",
            "per_page": per_page, "order_by": "publication_time", "currency": "RUR",
        }
        if sal_min:
            params["salary"] = sal_min
            params["only_with_salary"] = "true"
        try:
            resp = requests.get(self.HH_API, params=params, headers=self.HEADERS, timeout=10)
            resp.raise_for_status()
            return [self._parse_hh(item) for item in resp.json().get("items", [])]
        except Exception as e:
            logger.error(f"hh.ru API error: {e}")
            return []

    def _parse_hh(self, item: dict) -> dict:
        return {
            "id":          f"hh_{item['id']}",
            "title":       item["name"],
            "company":     item.get("employer", {}).get("name", ""),
            "salary":      self._fmt_salary(item.get("salary")),
            "format":      "Удалёнка",
            "description": item.get("snippet", {}).get("requirement", "") or "",
            "url":         item["alternate_url"],
        }

    @staticmethod
    def _fmt_salary(s: Optional[dict]) -> str:
        if not s:
            return "не указана"
        lo, hi, cur = s.get("from"), s.get("to"), s.get("currency", "RUR")
        cur = "₽" if cur == "RUR" else cur
        if lo and hi:  return f"{lo:,} – {hi:,} {cur}".replace(",", " ")
        if lo:         return f"от {lo:,} {cur}".replace(",", " ")
        if hi:         return f"до {hi:,} {cur}".replace(",", " ")
        return "не указана"
