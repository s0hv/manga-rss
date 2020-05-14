import logging
import re
from calendar import timegm
from datetime import datetime

import feedparser
import psycopg2
from psycopg2.extras import execute_values

from src.errors import FeedHttpError, InvalidFeedError
from src.scrapers.base_scraper import BaseScraper, BaseChapter
from src.utils.feedparsing import get_latest_entries
from src.utils.utilities import match_title, is_valid_feed, get_latest_chapters

logger = logging.getLogger('debug')


class Chapter(BaseChapter):
    URL_REGEX = re.compile(r'https://jaiminisbox.com/reader/read/(?P<manga_id>.+?)/(?P<chapter_identifier>\w+/\d+/\d+/)')
    MANGA_URL_PREFIX = 'https://jaiminisbox.com/reader/series/{}'

    def __init__(self, chapter_number, url, chapter_title=None,
                 manga_title=None, release_date=None, chapter_decimal=None,
                 **_):
        self._chapter_number = chapter_number
        self._chapter_decimal = chapter_decimal
        self._chapter_title = chapter_title
        self._manga_title = manga_title
        self._release_date = datetime.utcfromtimestamp(timegm(release_date)) if release_date else datetime.utcnow()

        m = self.URL_REGEX.match(url)
        m = m.groupdict()
        manga_id = m['manga_id']
        self._manga_url = self.MANGA_URL_PREFIX.format(manga_id)
        self._manga_id = manga_id
        self._chapter_identifier = manga_id + '/' + m['chapter_identifier'] + str(self._chapter_decimal or 0)

    @property
    def chapter_title(self):
        return self._chapter_title

    @property
    def chapter_number(self):
        return self._chapter_number

    @property
    def volume(self):
        return None

    @property
    def decimal(self):
        return self._chapter_decimal

    @property
    def release_date(self):
        return self._release_date

    @property
    def chapter_identifier(self):
        return self._chapter_identifier

    @property
    def manga_id(self):
        return self._manga_id

    @property
    def manga_title(self):
        return self._manga_title

    @property
    def manga_url(self):
        return self._manga_url

    @property
    def group(self):
        return "Jaimini's Box"

    @property
    def title(self):
        return self.chapter_title or f'Chapter {self.chapter_number}'


class JaiminisBox(BaseScraper):
    URL = 'https://jaiminisbox.com'
    FEED_URL = 'https://jaiminisbox.com/reader/feeds'
    CHAPTER_REGEX = re.compile(r'(?P<manga_title>.+?) +(?:(?:Chapter|Z=) ?(?P<chapter_number>\d+)(?:\.(?P<chapter_decimal>\d))?,?)(?::? (?P<chapter_title>.+))?')

    def scrape_series(self, title_id, service_id, manga_id):
        pass

    @staticmethod
    def min_update_interval():
        return JaiminisBox.UPDATE_INTERVAL

    def scrape_service(self, service_id, feed_url, last_update, title_id=None):
        feed = feedparser.parse(self.FEED_URL)
        try:
            is_valid_feed(feed)
        except (FeedHttpError, InvalidFeedError) as e:
            if isinstance(e, FeedHttpError):
                logger.info(str(e))
            else:
                logger.exception(f'Failed to fetch feed {feed_url}')

            try:
                self.dbutil.update_service_whole(None, service_id, self.min_update_interval())
            except psycopg2.Error:
                logger.exception(f'Failed to update service {feed_url}')
            return

        with self.conn as conn:
            with conn.cursor() as cur:
                sql = 'SELECT last_id FROM service_whole WHERE service_id=%s'
                cur.execute(sql, (service_id,))
                last_id = cur.fetchone()[0]

        titles = {}
        entries = get_latest_entries(feed.entries, last_id)
        if not entries:
            logger.info('No new entries found')
            try:
                self.dbutil.update_service_whole(None, service_id, self.min_update_interval())
            except psycopg2.Error:
                logger.exception(f'Failed to update service {feed_url}')
            return

        for post in entries:
            title = post.get('title', '')
            m = self.CHAPTER_REGEX.match(title)
            if not m:
                m = match_title(title)
                if not m:
                    logger.warning(f'Could not parse title from {title or post} with site native regex')
                    continue

                logger.debug(f'Fallback to universal regex successful on {title or post}')
                kwargs = m
            else:
                kwargs = m.groupdict()

            kwargs['url'] = post.link
            kwargs['release_date'] = post.published_parsed

            try:
                chapter = Chapter(**kwargs)
            except AttributeError:
                logger.exception('Failed to create chapter')
                continue

            manga_id = chapter.manga_id
            if manga_id in titles:
                titles[manga_id].append(chapter)
            else:
                titles[manga_id] = [chapter]

        if not titles:
            try:
                self.dbutil.update_service_whole(None, service_id, self.min_update_interval())
            except psycopg2.Error:
                logger.exception(f'Failed to update service {feed_url}')
            return

        data = []
        manga_ids = set()
        with self.conn:
            with self.conn.cursor() as cur:
                for row in self.dbutil.find_added_titles(cur, tuple(titles.keys())):
                    manga_id = row['manga_id']
                    manga_ids.add(manga_id)
                    for chapter in titles.pop(row['title_id']):
                        data.append((manga_id, service_id, chapter.title, chapter.chapter_number,
                                     chapter.decimal, chapter.chapter_identifier, chapter.release_date,
                                     chapter.group))

        if titles:
            with self.conn:
                with self.conn.cursor() as cur:
                    for manga_id, chapters in self.dbutil.add_new_series(cur, titles, service_id, True):
                        manga_ids.add(manga_id)
                        for chapter in chapters:
                            data.append((manga_id, service_id, chapter.title, chapter.chapter_number,
                                         chapter.decimal, chapter.chapter_identifier,
                                         chapter.release_date, chapter.group))

        sql = 'INSERT INTO chapters (manga_id, service_id, title, chapter_number, chapter_decimal, chapter_identifier, release_date, "group") VALUES ' \
              '%s ON CONFLICT DO NOTHING RETURNING manga_id, chapter_number, chapter_decimal, release_date'

        with self.conn:
            with self.conn.cursor() as cur:
                rows = execute_values(cur, sql, data, page_size=len(data), fetch=True)
                manga_ids = {r['manga_id'] for r in rows}
                if manga_ids:
                    self.dbutil.update_latest_release(cur, [(m,) for m in manga_ids])
                    self.dbutil.update_latest_chapter(cur, tuple(c for c in get_latest_chapters(rows).values()))

                sql = 'UPDATE service_whole SET last_id=%s WHERE service_id=%s'
                cur.execute(sql, (feed.entries[0].id, service_id))

                self.dbutil.update_service_whole(cur, service_id, self.min_update_interval())


        return manga_ids

