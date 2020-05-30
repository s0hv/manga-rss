import logging
import re
import time
from datetime import timedelta, datetime

import requests
from lxml import etree
from psycopg2.extras import execute_values

from src.scrapers.base_scraper import BaseScraper, BaseChapter
from src.utils.utilities import random_timedelta

logger = logging.getLogger('debug')
title_regex = re.compile(r'https:\\/\\/www\.comixology\.com\\/cart\\/add\\/subscription\\/(\d+)\\/0\?actionType=comic&actionId=\d+')
extra_regex = re.compile(r'.+? extra (\d+)\.(\d+)', re.I)


class Chapter(BaseChapter):
    def __init__(self, chapter_element, manga_title):
        title = chapter_element.cssselect('.content-info .content-subtitle')[0].text or ''

        if title.lower().startswith('vol'):
            self.invalid = True
            return
        self.invalid = False

        ch = title.split('#')[-1].split('.')
        if not title:
            title = chapter_element.cssselect('.content-info .content-title')[0].text or ''
            match = extra_regex.match(title)
            if match:
                ch = match.groups()
            elif not title.lower().endswith('extra'):
                logger.warning(f'Empty title for {manga_title} actual title {title}. Might be an extra issue')
            title = title.split(':')[-1] if ':' in title else 'Extra'

        try:
            self._chapter_number = int(ch[0] or 0)
        except ValueError:
            self._chapter_number = 0
        self._chapter_decimal = None
        if len(ch) > 1:
            self._chapter_decimal = int(ch[1])

        self._title = title
        self.url = chapter_element.cssselect('a.content-details')[0].attrib['href']
        self._chapter_identifier = chapter_element.cssselect('a.content-details')[0].attrib['href'].split('/')[-1]

        title_id = chapter_element.cssselect('.action-button.expand-action')[0].attrib.get('data-expand-menu-data', '')
        found = title_regex.findall(title_id)
        if not found:
            raise ValueError('Title id not found for comiXology chapter')

        if len(found) > 1:
            logger.warning(f'Multiple title ids found for {self.url}')

        self._title_id = found[0]
        self._manga_title = manga_title
        self.release_date_maybe = None

    def __repr__(self):
        return f'{self.manga_title} chapter {self.chapter_number}: {self.title}'

    @property
    def chapter_title(self):
        return self._title

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
        return self.release_date_maybe

    @property
    def chapter_identifier(self):
        return self._chapter_identifier

    @property
    def title_id(self):
        return self._title_id

    @property
    def manga_title(self):
        return self._manga_title

    @property
    def manga_url(self):
        return None

    @property
    def group(self):
        return 'comiXology'

    @property
    def title(self):
        return self.chapter_title


class ComiXology(BaseScraper):
    URL = 'https://www.comixology.com'
    NAME = 'ComiXology'
    CHAPTER_URL_FORMAT = 'https://www.comixology.com/chapter/digital-comic/{}'

    def __init__(self, conn, dbutil):
        super().__init__(conn, dbutil)
        self.service_id = None

    @staticmethod
    def min_update_interval():
        return random_timedelta(timedelta(hours=1), timedelta(hours=2))

    @staticmethod
    def wait():
        time.sleep(random_timedelta(timedelta(seconds=2), timedelta(seconds=10)).total_seconds())

    def scrape_series(self, title_id, service_id, manga_id):
        pass

    def scrape_service(self, service_id, feed_url, last_update, title_id=None):
        pass

    def get_chapter_release_date(self, url):
        r = requests.get(url)
        if r.status_code == 429:
            logger.error(f'Ratelimited on {self.URL}')
            return

        if r.status_code != 200:
            return

        root = etree.HTML(r.text)
        children = root.cssselect('.credits')[0].getchildren()

        for idx, c in enumerate(children):
            if 'digital release date' not in (c.text or '').lower().strip():
                continue

            d = children[idx + 1]
            try:
                return datetime.strptime(d.text, '%B %d %Y')
            except ValueError:
                logger.exception(f'Failed to convert release date to datetime, "{d.text}"')
                continue
            except IndexError:
                return

    def update_selected_manga(self, manga_links):
        now = datetime.utcnow()
        if self.service_id is None:
            self.service_id = self.dbutil.get_service(None, self.URL)

        if not self.service_id:
            logger.warning(f'No service found with {self.URL}')
            return

        for source in manga_links:
            manga = source.manga
            r = requests.get(source.manga_url)
            if r.status_code == 429:
                logger.error(f'Ratelimited on {self.URL}')
                return False

            if r.status_code != 200:
                self.wait()
                continue

            root = etree.HTML(r.text)
            chapter_elements = root.cssselect('.list-content.item-list li.content-item')
            if not chapter_elements:
                logger.warning(f'No chapters found for {source.manga_url}')
                self.wait()
                continue

            chapters = [Chapter(c, manga.title) for c in chapter_elements]
            sql = 'SELECT MAX(chapter_identifier::int) FROM chapters WHERE service_id=%s AND manga_id=%s'
            manga_id = manga.manga_id
            with self.conn:
                with self.conn.cursor() as cur:
                    cur.execute(sql, (self.service_id, manga_id))
                    row = cur.fetchone()
                    max_id = row[0] if row else None

            old_chapters = chapters
            if max_id:
                chapters = [c for c in chapters if not c.invalid and int(c.chapter_identifier) > max_id]

            if len(chapters) > 1:
                now = self.get_chapter_release_date(chapters[0].url) or now

            latest_chapter = manga.latest_chapter
            last_chapter = None
            for idx, chapter in enumerate(chapters):
                if chapter.invalid:
                    continue

                chapter.release_date_maybe = now

                if chapter.chapter_number == 0 and idx+1 != len(old_chapters):
                    chapter._chapter_number = old_chapters[idx+1].chapter_number
                    chapter._chapter_decimal = 5

                if last_chapter:
                    if not (chapter.chapter_number == last_chapter.chapter_number and chapter.decimal != last_chapter.decimal) and \
                            chapter.chapter_number != 0 and last_chapter.chapter_number - chapter.chapter_number > 1:
                        offset = latest_chapter - chapter.chapter_number
                        chapter.release_date_maybe = now - manga.release_interval * offset
                    else:
                        chapter.release_date_maybe = last_chapter.release_date_maybe - manga.release_interval

                last_chapter = chapter

            manga.release_date = now
            sql = 'INSERT INTO chapters (manga_id, service_id, title, chapter_number, chapter_decimal, chapter_identifier, release_date, "group") ' \
                  'VALUES %s ON CONFLICT DO NOTHING'
            args = []
            for c in chapters:
                if c.invalid:
                    continue
                args.append((manga_id, self.service_id, c.title, c.chapter_number, c.decimal, c.chapter_identifier, c.release_date, 'comiXology'))

            with self.conn:
                with self.conn.cursor() as cur:
                    if chapters:
                        execute_values(cur, sql, args, page_size=200)

                    sql = 'INSERT INTO manga_service (manga_id, service_id, disabled, last_check, title_id) VALUES ' \
                          '(%s, %s, TRUE, CURRENT_TIMESTAMP, %s) ON CONFLICT (manga_id, service_id) DO UPDATE SET ' \
                          'last_check=EXCLUDED.last_check'
                    cur.execute(sql, (manga.manga_id, self.service_id, manga.title_id))

            self.wait()

        self.set_checked(self.service_id)