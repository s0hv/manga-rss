from datetime import timedelta, datetime
from typing import Optional, Collection, Dict, Type

from psycopg2.extras import DictRow
from psycopg2.extensions import connection as Connection

from src.scrapers import base_scraper
from src.utils import dbutils


class Manga:
    def __init__(self, manga_id: Optional[int],
                 title: str,
                 release_interval: Optional[timedelta] = None,
                 latest_release: Optional[datetime] = None,
                 estimated_release: Optional[datetime] = None,
                 latest_chapter: Optional[int] = None,
                 ):
        self.manga_id = manga_id
        self.title = title
        self.release_interval = release_interval
        self.latest_release = latest_release
        self.estimated_release = estimated_release
        self.latest_chapter = latest_chapter

    @staticmethod
    def row_to_kwargs(row: DictRow) -> Dict:
        # TODO
        return {}

    @classmethod
    def from_dbrow(cls, row: DictRow):
        return cls(
            **cls.row_to_kwargs(row)
        )


class MangaInfo:
    def __init__(self, cover: Optional[str] = None,
                 status: Optional[int] = None,
                 artist: Optional[str] = None,
                 author: Optional[str] = None,
                 bookwalker: Optional[str] = None,
                 baka_updates: Optional[str] = None,
                 mal: Optional[str] = None,
                 amazon: Optional[str] = None,
                 ebook_japan: Optional[str] = None,
                 official_engtl: Optional[str] = None,
                 raw: Optional[str] = None,
                 novel_updates: Optional[str] = None,
                 kitsu: Optional[str] = None,
                 anime_planet: Optional[str] = None,
                 anilist: Optional[str] = None):
        self.cover = cover
        self.status = status
        self.artist = artist
        self.author = author
        self.bookwalker = bookwalker
        self.baka_updates = baka_updates
        self.mal = mal
        self.amazon = amazon
        self.ebook_japan = ebook_japan
        self.official_engtl = official_engtl
        self.raw = raw
        self.novel_updates = novel_updates
        self.kitsu = kitsu
        self.anime_planet = anime_planet
        self.anilist = anilist


class MangaService(Manga):
    def __init__(self, service_id: int,
                 disabled: bool,
                 title_id: str,
                 last_check: Optional[datetime] = None,
                 next_update: Optional[datetime] = None,
                 feed_url: Optional[str] = None,
                 latest_decimal: Optional[int] = None,
                 **kwargs):
        super().__init__(**kwargs)

        self.service_id = service_id
        self.disabled = disabled
        self.title_id = title_id
        self.last_check = last_check
        self.next_update = next_update
        self.feed_url = feed_url
        self.latest_decimal = latest_decimal

    @staticmethod
    def row_to_kwargs(row: DictRow) -> Dict:
        # TODO
        return super().row_to_kwargs(row)

    @classmethod
    def from_dbrow(cls, row: DictRow):
        return cls(
            **cls.row_to_kwargs(row)
        )

    # Returns a class initializer so it is named as a class would
    # noinspection PyPep8Naming
    @property
    def Scraper(self) -> Type['base_scraper.BaseScraper']:
        from src.scrapers import SCRAPERS
        return SCRAPERS[self.service_id]

    def scrape_series(self, conn: Connection, dbutil: 'dbutils.DbUtil'):
        scraper = self.Scraper(conn, dbutil)
        return scraper.scrape_series(self.title_id, self.service_id, self.manga_id, self.feed_url)
