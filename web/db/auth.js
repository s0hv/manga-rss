const pool = require('.');
const LRU = require("lru-cache");
const crypto = require('crypto');
const { bruteforce } = require('./../utils/ratelimits');

const sessionDebug = require('debug')('session-debug');
const authInfo = require('debug')('auth-info');

const userCache = new LRU(({
                max: 50,
                maxAge: 86400000, // 1 day in ms
                noDisposeOnSet: true,
                updateAgeOnGet: true,
}));

function generateAuthToken(uid, user_uuid, cb) {
    crypto.randomBytes(32+9, (err, buf) => {
    if (err) {
        return cb(err, false);
    }

    const token = buf.toString('base64', 0, 33);
    const lookup = buf.toString('base64', 33);

    const sql = `INSERT INTO auth_tokens (user_id, hashed_token, expires_at, lookup) VALUES ($1, encode(digest($2, 'sha256'), 'hex'), $3, $4)`;
    const age = 2592e+6; // 30 days
    pool.query(sql, [uid, token, new Date(Date.now() + age), lookup])
        .then(() => cb(null, `${lookup};${token};${Buffer.from(user_uuid).toString('base64')}`))
        .catch(err => cb(err, false));
    });
}
module.exports.generateAuthToken = generateAuthToken;

function regenerateAuthToken(uid, lookup, user_uuid, cb) {
    crypto.randomBytes(32, (err, buf) => {
    if (err) {
        return cb(err, false);
    }

    const token = buf.toString('base64');

    const sql = `UPDATE auth_tokens SET hashed_token=encode(digest($2, 'sha256'), 'hex') WHERE user_id=$1 AND lookup=$2 RETURNING expires_at`;
    pool.query(sql, [uid, lookup])
        .then(res => {
            if (res.rowCount === 0 || res.rows.length === 0) return cb(null, false);
            cb(null, `${lookup};${token};${Buffer.from(user_uuid).toString('base64')}`, res.rows[0].expires_at)
        })
        .catch(err => cb(err, false))
    });
}

module.exports.authenticate = function (req, email, password, cb) {
    if (password.length > 72) return cb(null, false);

    let sql = `SELECT user_id, username, user_uuid, theme FROM users WHERE email=$1 AND pwhash=crypt($2, pwhash)`
    pool.query(sql, [email, password])
        .then(res => {
        if (res.rowCount === 0) {
            return cb(null, false);
        }
        const row = res.rows[0];

        function setUser(row, token) {
            // Try to regen session
            req.session.regenerate((err)=>{
                if (err) {
                    console.error(err);
                    req.session.user_id = undefined;
                    return cb(err, false);
                }
                req.session.user_id = row.user_id;
                userCache.set(row.user_id, {
                    user_id: row.user_id,
                    username: row.username,
                    uuid: row.user_uuid,
                    theme: row.theme
                });
                return cb(null, token);
            });
}

        if (req.body.rememberme !== "on") {
            return setUser(row, true);
        }

        generateAuthToken(row.user_id, row.user_uuid, (err, token) => {
            if (err) return cb(err, false);
            setUser(row, token)
        })
        })
        .catch(err => {
            console.error(err);
            cb(err, false);
        });
}

function getUser(uid, cb) {
    if (!uid) return cb(null, null);

    let user = userCache.get(uid);
    if (user) return cb(user, null);

    const sql = `SELECT username, user_uuid, theme FROM users WHERE user_id=$1`;
    pool.query(sql, [uid])
         .then(res => {
            if (res.rowCount === 0) return cb(null, null);
            const row = res.rows[0];
            const val = {
                username: row.username,
                uuid: row.user_uuid,
                user_id: uid,
                theme: row.theme
            }
            userCache.set(uid, val);
            cb(val, null);
        })
        .catch(err => {
            console.error(err);
            cb(null, err);
        });
}
module.exports.getUser = getUser;

module.exports.requiresUser = function(req, res, next) {
    getUser(req.session.user_id, (user, err) => {
        req.user = user
        next(err);
    });
}

module.exports.checkAuth =  function(app) {
    return function (req, res, next) {
        if (req.session.user_id || !req.cookies.auth) return next();
        bruteforce.prevent(req, res, () => {

            authInfo('Checking auth from db for', req.cookies.auth);
            const sql = `SELECT u.user_id, u.username, u.user_uuid, u.theme FROM auth_tokens INNER JOIN users u on u.user_id=auth_tokens.user_id 
                         WHERE expires_at > NOW() AND user_uuid=$1 AND 
                               lookup=$2 AND hashed_token=encode(digest($3, 'sha256'), 'hex')`;

            /*
            Try to find the remember me token.
            If found associate current session with user and regenerate session id (this is important)
            If something fails or user isn't found we remove possible user id from session and continue
             */
            const [lookup, token, uuidb64] = req.cookies.auth.split(';', 3);
            if (!uuidb64) {
                res.clearCookie('auth');
                return next();
            }

            const uuid = Buffer.from(uuidb64, 'base64').toString('ascii');
            pool.query(sql, [uuid, lookup, token])
                .then(sqlRes => {
                    if (sqlRes.rowCount === 0) {
                        sessionDebug('Session not found. Clearing cookie')
                        res.clearCookie('auth');
                        req.session.user_id = undefined;

                        const checkLookup = `SELECT u.user_id FROM auth_tokens 
                                                              INNER JOIN users u ON auth_tokens.user_id = u.user_id 
                                             WHERE user_uuid=$1 AND lookup=$2`;

                        pool.query(checkLookup, [uuid, lookup])
                            .then(res2 => {
                                if (res2.rowCount === 0) return next();
                                // TODO Display warning
                                clearUserAuthTokens(res2.rows[0].user_id, () => {
                                    app.sessionStore.clearUserSessions(res2.rows[0].user_id, () => {
                                        sessionDebug("Invalid auth token found for user. Sessions cleared");
                                        next()
                                    })
                                })
                            })
                            .catch(next)
                        return;
                    }

                    const row = sqlRes.rows[0];
                    userCache.set(row.user_id, {
                        user_id: row.user_id,
                        username: row.username,
                        uuid: row.user_uuid,
                        theme: row.theme
                    });
                    // Try to regen session
                    req.session.regenerate((err)=>{
                        if (err) {
                            req.session.user_id = undefined;
                            return next(err);
                        }
                        regenerateAuthToken(row.user_id, lookup, uuid, (err, token, expiresAt) => {
                            if (err || !token) {
                                console.error('Failed to regenerate/change token', err);
                                return next(err);
                            }

                            req.session.user_id = row.user_id;
                            res.cookie('auth', token, {
                                httpOnly: true,
                                sameSite: 'strict',
                                expires: expiresAt
                            });
                            return next();
                        })
                    });
                })
                .catch(err => {
                    req.session.user_id = undefined;
                    if (err.code === '22P02') return next(err);
                    console.error(err);
                    next(err);
                })
        });
    }
}

function clearUserAuthToken(uid, auth, cb) {
    const [lookup, token] = auth.split(';', 3);

    const sql = `DELETE FROM auth_tokens WHERE user_id=$1 AND lookup=$2 AND hashed_token=encode(digest($3, 'sha256'), 'hex')`;
    pool.query(sql, [uid, lookup, token])
        .then(() => cb(null))
        .catch(err => cb(err));
}

module.exports.clearUserAuthToken = clearUserAuthToken;

function clearUserAuthTokens(uid, cb) {
    const sql = `DELETE FROM auth_tokens WHERE user_id=$1`;
    pool.query(sql, [uid])
        .then(() => cb(null))
        .catch(err => cb(err));
}

module.exports.clearUserAuthTokens = clearUserAuthTokens;

module.exports.modifyCacheUser = (uid, modifications) => {
    const user = userCache.get(uid);
    if (!user) return;
    userCache.set(uid, {...user, ...modifications});
}