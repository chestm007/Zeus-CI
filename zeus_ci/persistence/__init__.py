import json
import os
import sqlite3

from zeus_ci.runner import status_from_name, Status


class Build:
    def __init__(self, repo, ref, json_blob, status, build_id=None):
        self.id = build_id
        self.repo = repo
        self.ref = ref
        self.json = json.loads(json_blob) if type(json_blob) == str else json_blob
        self.status = status_from_name(status) if type(status) == str else status


class SqliteConnection:
    def __init__(self, db_filename='/tmp/zeus-ci.db'):
        db_is_new = db_filename == ':memory:' or not os.path.exists(db_filename)
        self.conn = sqlite3.connect(db_filename)
        if db_is_new:
            self._create_schema()

    def _create_schema(self):
        schema = """
        CREATE TABLE builds (
            id              integer PRIMARY KEY autoincrement NOT NULL,
            repo            text NOT NULL,
            ref             text NOT NULL,
            json_blob       text NOT NULL,
            status          text NOT NULL
        );
        """
        self.conn.execute(schema)

    def insert_build(self, build):
        query = """
        INSERT INTO builds (repo, ref, json_blob, status)
        VALUES (:repo, :ref, :json_blob, :status);
        """
        self.conn.execute(query, dict(repo=build.repo,
                                      ref=build.ref,
                                      json_blob=json.dumps(build.json),
                                      status=build.status.name))
        self.conn.commit()

    def update_build(self, id, status: Status):
        query = """
        UPDATE builds 
        SET status = :status 
        WHERE id = :id
        """
        self.conn.execute(query, dict(id=id, status=status.name))
        self.conn.commit()

    def get_builds(self, statuses: Status = None, build_id: int = None):
        query = """
        SELECT repo, ref, json_blob, status, id
        FROM builds
        """
        if build_id:
            query += "WHERE id = {}".format(build_id)
        if statuses:
            query += "WHERE status in ('{}')".format('\', \''.join(s.name for s in statuses))

        results = self.conn.execute(query)
        return list(map(lambda r: Build(*r), results.fetchall()))

