#!/usr/bin/python
# -*- coding: utf-8 -*-
from tmdbhelper.lib.addon.logger import kodi_log, TimerFunc
from tmdbhelper.lib.addon.plugin import get_setting, get_version
from tmdbhelper.lib.files.futils import FileUtils
import sqlite3

DEFAULT_TABLE = 'simplecache'
DATABASE_NAME = 'database_07'


class DatabaseCore:
    _basefolder = get_setting('cache_location', 'str') or ''
    _fileutils = FileUtils()
    _db_timeout = 60.0
    _db_read_timeout = 1.0
    database_version = 1
    database_changes = {}

    def __init__(self, folder=None, filename=None):
        '''Initialize our caching class'''
        folder = folder or DATABASE_NAME
        basefolder = f'{self._basefolder}{folder}'
        filename = filename or 'defaultcache.db'

        self._db_file = self._fileutils.get_file_path(basefolder, filename, join_addon_data=basefolder == folder)
        self._sc_name = f'{folder}_{filename}_databaserowfactory_{get_version()}'
        self.check_database_initialization()
        self.kodi_log(f"CACHE: Initialized: {self._sc_name} - Thread Safety Level: {sqlite3.threadsafety} - SQLite v{sqlite3.sqlite_version}")

    @property
    def window_home(self):
        from xbmcgui import Window
        return Window(10000)

    def get_window_property(self, name):
        return self.window_home.getProperty(name)

    def set_window_property(self, name, value):
        return self.window_home.setProperty(name, value)

    def del_window_property(self, name):
        return self.window_home.clearProperty(name)

    @property
    def database_init_property(self):
        return f'{self._sc_name}.database.init'

    @property
    def database_initialized(self):
        return self.get_window_property(self.database_init_property)

    def set_database_init(self):
        self.set_window_property(self.database_init_property, 'True')

    def del_database_init(self):
        self.del_window_property(self.database_init_property)

    @staticmethod
    def kodi_log(msg, level=0):
        kodi_log(msg, level)

    def check_database_initialization(self):
        if not self.database_initialized:
            self.init_database()

    def set_pragmas(self, connection):
        cursor = connection.cursor()
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        return connection

    def init_database(self):
        from jurialmunkey.locker import MutexPropLock
        with MutexPropLock(f'{self._db_file}.lockfile', kodi_log=self.kodi_log):
            database = self.create_database()
            self.set_database_init()
        return database

    def create_database(self):
        try:
            with TimerFunc(f'CACHE: Initialisation {self._db_file} took:'):
                self.kodi_log(f'CACHE: Initialising...\n{self._db_file}\n{self._sc_name}', 1)
                connection = sqlite3.connect(self._db_file, timeout=self._db_timeout)
                connection = self.set_pragmas(connection)
                connection = self.create_database_execute(connection)
            return connection
        except Exception as error:
            self.kodi_log(f'CACHE: Exception while initializing _database: {error}\n{self._sc_name}', 1)

    def get_database(self, read_only=False, log_level=1):
        timeout = self._db_read_timeout if read_only else self._db_timeout
        try:
            connection = sqlite3.connect(self._db_file, timeout=timeout)
        except Exception as error:
            self.kodi_log(f'CACHE: ERROR while retrieving _database: {error}\n{self._sc_name}', log_level)
            return None
        connection.row_factory = sqlite3.Row
        return self.set_pragmas(connection)

    def database_execute(self, connection, query, data=None):
        try:
            if not data:
                return connection.execute(query)
            if isinstance(data, list):
                return connection.executemany(query, data)
            return connection.execute(query, data)
        except sqlite3.OperationalError as operational_exception:
            self.kodi_log(f'CACHE: database OPERATIONAL ERROR! -- {operational_exception}\n{self._sc_name}\n--query--\n{query}\n--data--\n{data}', 2)
        except Exception as other_exception:
            self.kodi_log(f'CACHE: database OTHER ERROR! -- {other_exception}\n{self._sc_name}\n--query--\n{query}\n--data--\n{data}', 2)

    def execute_sql(self, query, data=None, read_only=False, connection=None):
        try:
            if connection:
                return self.database_execute(connection, query, data=data)
            with self.get_database(read_only=read_only) as conn:
                return self.database_execute(conn, query, data=data)
        except Exception as database_exception:
            self.kodi_log(f'CACHE: database GET DATABASE ERROR! -- {database_exception}\n{self._sc_name} -- read_only: {read_only}', 2)

    @property
    def database_tables(self):
        return {}

    def create_database_execute(self, connection):
        def create_column_data(columns):
            return [f'{k} {v["data"]}' for k, v in columns.items()]
        
        def create_column_fkey(columns):
            return [f'FOREIGN KEY({k}) REFERENCES {v["foreign_key"]} ON DELETE CASCADE' for k, v in columns.items() if 'foreign_key' in v]

        def create_column_uids(columns):
            keys = [k for k, v in columns.items() if v.get('unique')]
            return [f'UNIQUE ({", ".join(keys)})'] if keys else []

        cursor = connection.cursor()
        this_database_version = cursor.execute("PRAGMA user_version").fetchone()[0]

        if this_database_version and this_database_version < self.database_version:
            for version, changes in self.database_changes.items():
                if version <= this_database_version: continue
                for query in changes:
                    try: cursor.execute(query)
                    except Exception as error: self.kodi_log(f'CACHE: Exception while initializing _database: {error}\n{self._sc_name} - {query}', 1)

        for table, columns in self.database_tables.items():
            query_parts = create_column_data(columns) + create_column_fkey(columns) + create_column_uids(columns)
            query = f'CREATE TABLE IF NOT EXISTS {table}({", ".join(query_parts)})'
            try: cursor.execute(query)
            except Exception as error: self.kodi_log(f'CACHE: Exception while initializing _database: {error}\n{self._sc_name} - {query}', 1)

        for table, columns in self.database_tables.items():
            for column, v in columns.items():
                if not v.get('indexed'): continue
                query = f'CREATE INDEX IF NOT EXISTS {table}_{column}_x ON {table}({column})'
                try: cursor.execute(query)
                except Exception as error: self.kodi_log(f'CACHE: Exception while initializing _database: {error}\n{self._sc_name} - {query}', 1)

        if this_database_version < self.database_version:
            try:
                query = f"PRAGMA user_version = {self.database_version}"
                cursor.execute(query)
            except Exception as error: self.kodi_log(f'CACHE: Exception while initializing _database: {error}\n{self._sc_name} - {query}', 1)

        return connection


class DatabaseStatements:
    @staticmethod
    def insert_or_ignore(table, keys=('id',)):
        return f"INSERT OR IGNORE INTO {table}({', '.join(keys)}) VALUES ({', '.join(['?' for _ in keys])})"

    @staticmethod
    def insert_or_replace(table, keys=('id',)):
        return f"INSERT OR REPLACE INTO {table}({', '.join(keys)}) VALUES ({', '.join(['?' for _ in keys])})"

    @staticmethod
    def insert_or_update_if_null(table, keys=('id',), conflict_constraint='id'):
        update_keys = ', '.join([f'{k}=ifnull({k},excluded.{k})' for k in keys])
        return f"INSERT INTO {table}({', '.join(keys)}) VALUES ({', '.join(['?' for _ in keys])}) ON CONFLICT ({conflict_constraint}) DO UPDATE SET {update_keys}"

    @staticmethod
    def delete_keys(table, keys, conditions='item_type=?'):
        update_keys = ', '.join([f'{k}=NULL' for k in keys])
        conditions_str = f'WHERE {conditions}' if conditions else ''
        return f'UPDATE {table} SET {update_keys} {conditions_str}'

    @staticmethod
    def delete_item(table, conditions='id=?'):
        return f'DELETE FROM {table} WHERE {conditions}'

    @staticmethod
    def update_if_null(table, keys, conditions='id=?'):
        update_keys = ', '.join([f'{k}=ifnull(?,{k})' for k in keys])
        return f'UPDATE {table} SET {update_keys} WHERE {conditions}'

    @staticmethod
    def select_limit(table, keys, conditions='id=?'):
        return f"SELECT {', '.join(keys)} FROM {table} WHERE {conditions} LIMIT 1"

    @staticmethod
    def select(table, keys, conditions=None):
        conditions_str = f' WHERE {conditions}' if conditions else ''
        return f"SELECT {', '.join(keys)} FROM {table}{conditions_str}"


class DatabaseMethod:
    def set_list_values(self, table=DEFAULT_TABLE, keys=(), values=(), overwrite=False, connection=None):
        if not values: return
        statement = DatabaseStatements.insert_or_replace if overwrite else DatabaseStatements.insert_or_ignore
        self.execute_sql(statement(table, keys), values, connection=connection)

    def get_list_values(self, table=DEFAULT_TABLE, keys=(), values=(), conditions=None, connection=None):
        cursor = self.execute_sql(DatabaseStatements.select(table, keys, conditions), data=values, read_only=True, connection=connection)
        return cursor.fetchall() if cursor else None

    def del_list_values(self, table=DEFAULT_TABLE, values=(), conditions=None, connection=None):
        self.execute_sql(DatabaseStatements.delete_item(table, conditions), data=values, connection=connection)

    def set_or_update_null_list_values(self, table=DEFAULT_TABLE, keys=(), values=(), conflict_constraint='id', connection=None):
        if not values: return
        statement = DatabaseStatements.insert_or_update_if_null
        self.execute_sql(statement(table, keys, conflict_constraint=conflict_constraint), values, connection=connection)

    def get_values(self, table=DEFAULT_TABLE, item_id=None, keys=(), connection=None):
        cursor = self.execute_sql(DatabaseStatements.select_limit(table, keys), data=(item_id,), read_only=True, connection=connection)
        return cursor.fetchone() if cursor else None

    def set_item_values(self, table=DEFAULT_TABLE, item_id=None, keys=(), values=(), connection=None):
        def _transaction(conn):
            self.create_item(table=table, item_id=item_id, connection=conn)
            self.execute_sql(DatabaseStatements.update_if_null(table, keys), data=(*values, item_id), connection=conn)
        
        if connection: _transaction(connection)
        else:
            with self.get_database() as conn: _transaction(conn)

    def set_many_values(self, table=DEFAULT_TABLE, keys=(), data=None, connection=None):
        if not data: return
        def _transaction(conn):
            self.create_many_items(table=table, item_ids=list(data.keys()), connection=conn)
            self.execute_sql(DatabaseStatements.update_if_null(table, keys), data=[(*values, item_id) for item_id, values in data.items()], connection=conn)

        if connection: _transaction(connection)
        else:
            with self.get_database() as conn: _transaction(conn)

    def del_column_values(self, table=DEFAULT_TABLE, keys=(), item_type=None, connection=None):
        conditions = 'item_type=?' if item_type is not None else None
        data = (item_type,) if item_type is not None else None
        self.execute_sql(DatabaseStatements.delete_keys(table, keys, conditions=conditions), data=data, connection=connection)

    def del_item(self, table=DEFAULT_TABLE, item_id=None, connection=None):
        self.execute_sql(DatabaseStatements.delete_item(table), data=(item_id,), connection=connection)

    def del_item_like(self, table=DEFAULT_TABLE, item_id=None, connection=None):
        self.execute_sql(DatabaseStatements.delete_item(table, conditions='id LIKE ?'), data=(item_id,), connection=connection)

    def create_item(self, table=DEFAULT_TABLE, item_id=None, connection=None):
        self.execute_sql(DatabaseStatements.insert_or_ignore(table), data=(item_id,), connection=connection)

    def create_many_items(self, table=DEFAULT_TABLE, item_ids=(), connection=None):
        if not item_ids: return
        self.execute_sql(DatabaseStatements.insert_or_ignore(table), data=[(item_id,) for item_id in item_ids], connection=connection)


class Database(DatabaseCore, DatabaseMethod):
    pass