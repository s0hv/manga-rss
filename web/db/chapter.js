const db = require('.');

module.exports.getChapterReleases = (mangaId) => {
  const sql = `SELECT extract(EPOCH FROM date_trunc('day', release_date)) as "timestamp", CAST(count(release_date) as int) count 
               FROM chapters 
               WHERE manga_id=$1 GROUP BY 1 ORDER BY 1`;

  return db.query(sql, [mangaId])
    .then(res => res.rows);
};

module.exports.addChapter = ({
  mangaId,
  serviceId,
  title,
  chapterNumber,
  chapterDecimal,
  releaseDate,
  chapterIdentifier,
  group,
}) => {
  const sql = `INSERT INTO chapters (manga_id, service_id, title, chapter_number, chapter_decimal, release_date, chapter_identifier, "group") 
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               RETURNING chapter_id`;
  return db.query(sql, [mangaId, serviceId, title, chapterNumber, chapterDecimal, releaseDate, chapterIdentifier, group])
    .then(res => res.rows[0]?.chapter_id);
};

module.exports.getChapters = (mangaId, limit, offset) => {
  const sql = `
    SELECT
        COUNT(*) as count,
        (
            SELECT json_agg(ch)
            FROM (
                SELECT
                    chapter_id,
                    title,
                    chapter_number,
                    EXTRACT(EPOCH from release_date) as release_date,
                    "group",
                    service_id,
                    chapter_identifier as chapter_url
                FROM chapters WHERE manga_id=$1
                ORDER BY chapter_number DESC, chapter_decimal DESC NULLS LAST
                LIMIT $2 ${offset ? 'OFFSET $3' : ''}
            ) as ch
        ) as chapters,
       (exists(SELECT 1 FROM manga WHERE manga_id=$1)) as "exists"
    FROM chapters
    INNER JOIN manga m ON m.manga_id = chapters.manga_id
    WHERE m.manga_id=$1
  `;

  const args = [mangaId, limit];
  if (offset) args.push(offset);

  return db.query(sql, args)
    .then(res => {
      const row = res.rows[0];
      if (!row || !row.exists) return Promise.resolve(null);

      return Promise.resolve({
        count: row.count,
        chapters: row.chapters,
      });
    });
};
