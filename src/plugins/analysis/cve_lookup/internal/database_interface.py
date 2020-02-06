import logging
import sys
from contextlib import suppress
from pathlib import Path
from sqlite3 import Error as SqliteException
from sqlite3 import connect

try:
    from ..internal.helper_functions import get_field_string, get_field_names
except (ImportError, SystemError):
    sys.path.append(str(Path(__file__).parent.parent / 'internal'))
    from helper_functions import get_field_string, get_field_names

DB_PATH = str(Path(__file__).parent / 'cve_cpe.db')

CPE_DB_FIELDS = [
    ('cpe_id', 'TEXT'), ('part', 'TEXT'), ('vendor', 'TEXT'), ('product', 'TEXT'), ('version', 'TEXT'),
    ('\'update\'', 'TEXT'), ('edition', 'TEXT'), ('language', 'TEXT'), ('sw_edition', 'TEXT'), ('target_sw', 'TEXT'),
    ('target_hw', 'TEXT'), ('other', 'TEXT'),
]
CVE_DB_FIELDS = [
    ('cve_id', 'TEXT'), ('year', 'INTEGER'), ('cpe_id', 'TEXT'), ('cvss_v2_score', 'TEXT'), ('cvss_v3_score', 'TEXT'),
    ('part', 'TEXT'), ('vendor', 'TEXT'), ('product', 'TEXT'), ('version', 'TEXT'), ('\'update\'', 'TEXT'),
    ('edition', 'TEXT'), ('language', 'TEXT'), ('sw_edition', 'TEXT'), ('target_sw', 'TEXT'), ('target_hw', 'TEXT'),
    ('other', 'TEXT'), ('version_start_including', 'TEXT'), ('version_start_excluding', 'TEXT'),
    ('version_end_including', 'TEXT'), ('version_end_excluding', 'TEXT')
]
CVE_SUMMARY_DB_FIELDS = [
    ('cve_id', 'TEXT'), ('year', 'INTEGER'), ('summary', 'TEXT'), ('cvss_v2_score', 'TEXT'), ('cvss_v3_score', 'TEXT')
]

TABLE_CREATION_COMMAND = 'CREATE TABLE IF NOT EXISTS {{}} ({})'
TABLE_INSERT_COMMAND = 'INSERT INTO {{}} ({}) VALUES ({})'

QUERIES = {
    'cpe_lookup': 'SELECT DISTINCT vendor, product, version FROM cpe_table',
    'create_cpe_table': TABLE_CREATION_COMMAND.format(get_field_string(CPE_DB_FIELDS)),
    'create_cve_table': TABLE_CREATION_COMMAND.format(get_field_string(CVE_DB_FIELDS)),
    'create_summary_table': TABLE_CREATION_COMMAND.format(get_field_string(CVE_SUMMARY_DB_FIELDS)),
    'cve_lookup': 'SELECT cve_id, vendor, product, version, cvss_v2_score, cvss_v3_score, version_start_including, '
                  'version_start_excluding, version_end_including, version_end_excluding FROM cve_table',
    'delete_outdated': 'DELETE FROM {} WHERE cve_id IN (SELECT cve_id FROM {})',
    'drop': 'DROP TABLE IF EXISTS {}',
    'exist': 'SELECT name FROM sqlite_master WHERE type=\'table\' AND name=\'{}\'',
    'extract_relevant': 'SELECT * FROM {} AS new WHERE new.year IN (SELECT distinct(year) FROM {})',
    'get_years_from_cve': 'SELECT DISTINCT year FROM cve_table',
    'insert_cpe': TABLE_INSERT_COMMAND.format(get_field_names(CPE_DB_FIELDS), ', '.join(['?'] * len(CPE_DB_FIELDS))),
    'insert_cve': TABLE_INSERT_COMMAND.format(get_field_names(CVE_DB_FIELDS), ', '.join(['?'] * len(CVE_DB_FIELDS))),
    'insert_summary': TABLE_INSERT_COMMAND.format(
        get_field_names(CVE_SUMMARY_DB_FIELDS), ', '.join(['?'] * len(CVE_SUMMARY_DB_FIELDS))),
    'select_all': 'SELECT * FROM {}',
    'summary_lookup': 'SELECT cve_id, summary, cvss_v2_score, cvss_v3_score FROM summary_table',
    'test_create': 'CREATE TABLE IF NOT EXISTS {} (x INTEGER)',
    'test_create_update': 'CREATE TABLE IF NOT EXISTS {} (cve_id TEXT NOT NULL, year INTEGER NOT NULL)',
    'test_insert': 'INSERT INTO {} (x) VALUES (?)',
    'test_insert_cve_id': 'INSERT INTO {} (cve_id, year) VALUES (?, ?)'
}


class DatabaseInterface:
    '''
    class to provide connections to a sqlite database and allows to operate on it
    '''

    def __init__(self, db_path: str = DB_PATH):
        self.connection = None
        self.cursor = None
        if not db_path.endswith('.db') and isinstance(db_path, str):
            raise TypeError('Input must be string and end on \'.db\'')
        try:
            self.connection = connect(db_path)
        except SqliteException as exception:
            logging.warning('Could not connect to CPE database: {} {}'.format(type(exception).__name__, exception))
            raise exception

    def table_manager(self, query: str):
        try:
            self.cursor = self.connection.cursor()
            self.cursor.execute(query)
        finally:
            self.cursor.close()

    def select_query(self, query: str):
        try:
            self.cursor = self.connection.cursor()
            self.cursor.execute(query)
            while True:
                outputs = self.cursor.fetchmany(10000)
                if not outputs:
                    break
                for output in outputs:
                    yield output
        finally:
            self.cursor.close()

    def select_single(self, query: str) -> tuple:
        return list(self.select_query(query))[0]

    def insert_rows(self, query: str, input_data: list):
        try:
            self.cursor = self.connection.cursor()
            self.cursor.executemany(query, input_data)
            self.connection.commit()
        finally:
            self.cursor.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.connection:
            with suppress(SqliteException):
                self.connection.close()