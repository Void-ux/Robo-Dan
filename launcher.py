from __future__ import annotations

import re
import os
import sys
import json
import uuid
import click
import logging
import asyncio
import datetime
import traceback
from pathlib import Path
from urllib.parse import quote
from logging.handlers import RotatingFileHandler
from typing import TypedDict, Any

import aiob2
import aiohttp
import asyncpg
import discord
import mystbin
import toml

from bot import RoboDan, Config
from cogs import EXTENSIONS


try:
    import uvloop
except Exception:
    pass
else:
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

discord.opus._load_default()

os.environ['JISHAKU_FORCE_PAGINATOR'] = "True"
os.environ['JISHAKU_NO_UNDERSCORE'] = "True"
os.environ['JISHAKU_NO_DM_TRACEBACK'] = "True"
os.environ['JISHAKU_HIDE'] = "True"


with open('config.toml') as file:
    config: Config = toml.load(file)  # type: ignore


def _create_uri(conf: Config) -> str:
    return "postgresql://{}:{}@{}:{}/{}".format(
        conf['database']['user'],
        quote(conf['database']['password']),
        conf['database']['host'],
        conf['database'].get('port', 5432),
        conf['database']['database']
    )


class Revisions(TypedDict):
    # The version key represents the current activated version
    # So v1 means v1 is active and the next revision should be v2
    # In order for this to work the number has to be monotonically increasing
    # and have no gaps
    version: int
    database_uri: str


REVISION_FILE = re.compile(r'(?P<kind>V|U)(?P<version>[0-9]+)__(?P<description>.+).sql')


class Revision:
    __slots__ = ('kind', 'version', 'description', 'file')

    def __init__(self, *, kind: str, version: int, description: str, file: Path) -> None:
        self.kind: str = kind
        self.version: int = version
        self.description: str = description
        self.file: Path = file

    @classmethod
    def from_match(cls, match: re.Match[str], file: Path):
        return cls(
            kind=match.group('kind'), version=int(match.group('version')), description=match.group('description'), file=file
        )


class Migrations:
    def __init__(self, *, filename: str = 'postgres/migrations/revisions.json'):
        self.filename: str = filename
        self.root: Path = Path(filename).parent
        self.revisions: dict[int, Revision] = self.get_revisions()
        self.load()

    def ensure_path(self) -> None:
        self.root.mkdir(exist_ok=True)

    def load_metadata(self) -> Revisions:
        try:
            with open(self.filename, 'r', encoding='utf-8') as fp:
                return json.load(fp)
        except FileNotFoundError:
            return {
                'version': 0,
                'database_uri': discord.utils.MISSING,
            }

    def get_revisions(self) -> dict[int, Revision]:
        result: dict[int, Revision] = {}
        for file in self.root.glob('*.sql'):
            match = REVISION_FILE.match(file.name)
            if match is not None:
                rev = Revision.from_match(match, file)
                result[rev.version] = rev

        return result

    def dump(self) -> Revisions:
        return {
            'version': self.version,
            'database_uri': self.database_uri,
        }

    def load(self) -> None:
        self.ensure_path()
        data = self.load_metadata()
        self.version: int = data['version']
        self.database_uri: str = data['database_uri']

    def save(self):
        temp = f'{self.filename}.{uuid.uuid4()}.tmp'
        with open(temp, 'w', encoding='utf-8') as tmp:
            json.dump(self.dump(), tmp)

        # atomically move the file
        os.replace(temp, self.filename)

    def is_next_revision_taken(self) -> bool:
        return self.version + 1 in self.revisions

    @property
    def ordered_revisions(self) -> list[Revision]:
        return sorted(self.revisions.values(), key=lambda r: r.version)

    def create_revision(self, reason: str, *, kind: str = 'V') -> Revision:
        cleaned = re.sub(r'\s', '_', reason)
        filename = f'{kind}{self.version + 1}__{cleaned}.sql'
        path = self.root / filename

        stub = (
            f'-- Revises: V{self.version}\n'
            f'-- Creation Date: {datetime.datetime.utcnow()} UTC\n'
            f'-- Reason: {reason}\n\n'
        )

        with open(path, 'w', encoding='utf-8', newline='\n') as fp:
            fp.write(stub)

        self.save()
        return Revision(kind=kind, description=reason, version=self.version + 1, file=path)

    async def upgrade(self, connection: asyncpg.Connection) -> int:
        ordered = self.ordered_revisions
        successes = 0
        async with connection.transaction():
            for revision in ordered:
                if revision.version > self.version:
                    sql = revision.file.read_text('utf-8')
                    await connection.execute(sql)
                    successes += 1

        self.version += successes
        self.save()
        return successes

    def display(self) -> None:
        ordered = self.ordered_revisions
        for revision in ordered:
            if revision.version > self.version:
                sql = revision.file.read_text('utf-8')
                click.echo(sql)


class RemoveNoise(logging.Filter):
    def __init__(self) -> None:
        super().__init__(name="discord.state")

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelname == "WARNING" and "referencing an unknown" in record.msg:
            return False
        return True


class ColourFormatter(logging.Formatter):

    # ANSI codes are a bit weird to decipher if you're unfamiliar with them, so here's a refresher
    # It starts off with a format like \x1b[XXXm where XXX is a semicolon separated list of commands
    # The important ones here relate to colour.
    # 30-37 are black, red, green, yellow, blue, magenta, cyan and white in that order
    # 40-47 are the same except for the background
    # 90-97 are the same but "bright" foreground
    # 100-107 are the same as the bright ones but for the background.
    # 1 means bold, 2 means dim, 0 means reset, and 4 means underline.

    LEVEL_COLOURS = [
        (logging.DEBUG, '\x1b[40;1m'),
        (logging.INFO, '\x1b[32;1m'),
        (logging.WARNING, '\x1b[33;1m'),
        (logging.ERROR, '\x1b[31m'),
        (logging.CRITICAL, '\x1b[41m'),
    ]

    FORMATS = {
        level: logging.Formatter(
            f'[\x1b[30;1m%(asctime)s\x1b[0m][ {colour}%(levelname)-8s\x1b[0m] \x1b[31m%(name)s\x1b[0m %(message)s',
            '%Y-%m-%d %H:%M:%S',
        )
        for level, colour in LEVEL_COLOURS
    }

    def format(self, record):
        formatter = self.FORMATS.get(record.levelno)
        if formatter is None:
            formatter = self.FORMATS[logging.DEBUG]

        # Override the traceback to always print in red
        if record.exc_info:
            text = formatter.formatException(record.exc_info)
            record.exc_text = f'\x1b[31m{text}\x1b[0m'

        output = formatter.format(record)

        # Remove the cache layer
        record.exc_text = None
        return output


class SetupLogging:
    def __init__(self, *, stream: bool = True) -> None:
        self.log: logging.Logger = logging.getLogger()
        self.max_bytes: int = 32 * 1024
        self.logging_path = Path("./logs/")
        self.logging_path.mkdir(exist_ok=True)
        self.stream: bool = stream

    def __enter__(self):
        logging.getLogger("discord").setLevel(logging.INFO)
        logging.getLogger("discord.http").setLevel(logging.INFO)
        logging.getLogger("discord.state").addFilter(RemoveNoise())
        # Prevent logging every GET request made by Prometheus as it completely
        # floods the terminal.
        logging.getLogger('aiohttp.access').setLevel(logging.WARNING)
        logging.getLogger('aiob2').setLevel(logging.DEBUG)

        self.log.setLevel(logging.INFO)
        handler = RotatingFileHandler(
            filename=self.logging_path / "robodan.log", encoding="utf-8", mode="w", maxBytes=self.max_bytes, backupCount=5
        )
        fmt = ColourFormatter()
        handler.setFormatter(fmt)
        self.log.addHandler(handler)

        if self.stream:
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(fmt)
            self.log.addHandler(stream_handler)

        return self

    def __exit__(self, *args: Any) -> None:
        handlers = self.log.handlers[:]
        for hdlr in handlers:
            hdlr.close()
            self.log.removeHandler(hdlr)


async def create_pool() -> asyncpg.Pool:
    def _encode_jsonb(value):
        return json.dumps(value)

    def _decode_jsonb(value):
        return json.loads(value)

    async def init(con):
        await con.set_type_codec(
            'jsonb',
            schema='pg_catalog',
            encoder=_encode_jsonb,
            decoder=_decode_jsonb,
            format='text',
        )

    return await asyncpg.create_pool(
        _create_uri(config),
        init=init,
        command_timeout=300,
        max_size=20,
        min_size=20,
    )  # type: ignore


async def run_bot():
    log_ = logging.getLogger('robodan')
    try:
        pool = await create_pool()
    except Exception:
        click.echo('Could not set up PostgreSQL. Exiting.', file=sys.stderr)
        log_.exception('Could not set up PostgreSQL. Exiting.')
        return

    async with RoboDan(config) as bot:
        bot.pool = pool
        bot.session = aiohttp.ClientSession()
        bot.bucket = aiob2.Client(
            bot.config['backblaze']['key_id'],
            bot.config['backblaze']['key'], 
            log_handler=None
        )
        bot.mystbin = mystbin.Client()

        for extension in EXTENSIONS:
            await bot.load_extension(extension)
        await bot.load_extension("jishaku")

        asyncio.create_task(bot.startup_message())
        await bot.start()


@click.group(invoke_without_command=True, options_metavar='[options]')
@click.pass_context
def main(ctx):
    """Launches the bot."""
    if ctx.invoked_subcommand is None:
        with SetupLogging():
            asyncio.run(run_bot())


@main.group(short_help='database stuff', options_metavar='[options]')
def db():
    pass


async def ensure_uri_can_run(uri) -> bool:
    connection: asyncpg.Connection = await asyncpg.connect(uri)
    await connection.close()
    return True


@db.command()
def init():
    """Initializes the database and runs all the current migrations"""

    migrations = Migrations()
    asyncio.run(ensure_uri_can_run(migrations.database_uri))

    try:
        applied = asyncio.run(run_upgrade(migrations))
    except Exception:
        traceback.print_exc()
        click.secho('failed to initialize and apply migrations due to error', fg='red')
    else:
        click.secho(f'Successfully initialized and applied {applied} revisions(s)', fg='green')


@db.command()
@click.option('--reason', '-r', help='The reason for this revision.', required=True)
def migrate(reason):
    """Creates a new revision for you to edit."""
    migrations = Migrations()
    if migrations.is_next_revision_taken():
        click.echo('an unapplied migration already exists for the next version, exiting')
        click.secho('hint: apply pending migrations with the `upgrade` command', bold=True)
        return

    revision = migrations.create_revision(reason)
    click.echo(f'Created revision V{revision.version!r}')


async def run_upgrade(migrations: Migrations) -> int:
    connection: asyncpg.Connection = await asyncpg.connect(migrations.database_uri)
    return await migrations.upgrade(connection)


@db.command()
@click.option('--sql', help='Print the SQL instead of executing it', is_flag=True)
def upgrade(sql):
    """Upgrades the database at the given revision (if any)."""
    migrations = Migrations()

    if sql:
        migrations.display()
        return

    try:
        applied = asyncio.run(run_upgrade(migrations))
    except Exception:
        traceback.print_exc()
        click.secho('failed to apply migrations due to error', fg='red')
    else:
        click.secho(f'Applied {applied} revisions(s)', fg='green')


@db.command()
def current():
    """Shows the current active revision version"""
    migrations = Migrations()
    click.echo(f'Version {migrations.version}')


@db.command()
@click.option('--reverse', help='Print in reverse order (oldest first).', is_flag=True)
def log(reverse):
    """Displays the revision history"""
    migrations = Migrations()
    # Revisions is oldest first already
    revs = reversed(migrations.ordered_revisions) if not reverse else migrations.ordered_revisions
    for rev in revs:
        as_yellow = click.style(f'V{rev.version:>03}', fg='yellow')
        click.echo(f'{as_yellow} {rev.description.replace("_", " ")}')


if __name__ == '__main__':
    main()
