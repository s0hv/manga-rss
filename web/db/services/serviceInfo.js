const pool = require('..');

function getServices() {
  const sql = `SELECT s.service_id id, service_name, disabled, url, s.last_check, sw.next_update
               FROM services s LEFT JOIN service_whole sw ON s.service_id = sw.service_id`;

  return pool.query(sql);
}

module.exports.getServices = getServices;