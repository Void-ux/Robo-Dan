from __future__ import annotations

import datetime
import functools
import re
from dataclasses import dataclass
from typing import Optional, Union, TypeVar, List, Sized, Iterable

import discord
from unidecode import unidecode

ACCEPTABLE_FORMATS = [
    'video/mp4',
    'image/jpeg',
    'image/png',
    'image/gif',
    'video/quicktime'
]


TIME_CONVERSIONS = {
    's': 1,
    'm': 60,
    'h': 3600,
    'd': 86400,
    'w': 604800,
    'mo': 2628000
}


_URL_REGEX: re.Pattern = re.compile(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*(),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+')  # noqa
ID_REGEX = re.compile(r'([0-9]{15,20})')  # noqa


@dataclass
class Report:
    reporter: Union[discord.Member, int]
    offender: Union[discord.Member, int]
    category: str
    comments: str
    evidence: str
    investigator: Optional[int] = None

    _URL_REGEX: re.Pattern = re.compile(r'(?:(?:https?|ftp):\/\/)?[\w/\-?=%.]+\.[\w/\-&?=%.]+')  # noqa

    @classmethod
    def from_embed(cls,
                   *,
                   embed: discord.Embed
                   ) -> Report:
        # Any of the following in the 'list' will be replaced with ''
        mention_pattern = r'[<@!>]'
        data = {
            'reporter': int(re.sub(mention_pattern, '', embed.fields[2].value)),
            'offender': int(re.sub(mention_pattern, '', embed.fields[3].value)),
            'category': re.sub(r'\*', '', embed.fields[0].name),
            'comments': embed.fields[1].value,
            'evidence': embed.fields[0].value[10:]
        }
        if embed.description:
            data['investigator'] = int(re.sub(mention_pattern, '', embed.description.split()[1]))

        return cls(**data)

    @functools.cached_property
    def evidence_urls(self):
        return self._URL_REGEX.findall(self.evidence)

    def __str__(self):
        return f'<Report reporter={self.reporter} offender={self.offender} category={self.category} ' \
               f'comments={self.comments} evidence={self.evidence} investigator={self.investigator}>'


_Attachment = TypeVar('_Attachment', bound='Attachment')


@dataclass
class Attachment:
    """
    A class to represent a basic attachments (image/video mainly).

    ...

    Attributes
    ----------
    name : str
        Name of the attachment
    url : str
        The url of the attachment for HTTP clients to use
    content_type: str
        The content type e.g. video/mp4
    size : int
        The number of bytes the attachment has
    content_bytes : int
        The actual contents of the file

    Methods
    -------
    from_response(name="", url="", res, content_type=""):
        Constructs an Attachment from an aiohttp.ClientResponse
    """

    name: str
    url: str
    content_type: str
    size: int
    content_bytes: bytes

    # If you create an aiohttp.ClientResponse in a func first, and want a (list of) Attachment(s) later.
    @classmethod
    def from_response(
        cls: _Attachment, name: str, url: str, res: bytes, content_type: str
    ) -> _Attachment:
        return cls(
            name,
            url,
            content_type,
            len(res),
            res,
        )


class TabularData:
    def __init__(self, ascii: bool = False):
        self.ascii = ascii
        self._widths: List[int] = []
        self._columns: List[str] = []
        self._rows: List[List[str]] = []

    def set_columns(self, columns: Iterable[Sized]):
        if self.ascii:
            self._columns = [unidecode(str(e)) for e in columns]
        else:
            self._columns = [str(e) for e in columns]
        self._widths = [len(c) + 2 for c in columns]

    def add_row(self, row: Iterable[Sized | int]):
        if self.ascii:
            row = [unidecode(str(e)) for e in row]
        else:
            row = [str(e) for e in row]
        self._rows.append(row)

        for index, element in enumerate(row):
            width = len(element) + 2
            if width > self._widths[index]:
                self._widths[index] = width

    def add_rows(self, rows: Iterable[Iterable[Sized | int]]):
        for row in rows:
            self.add_row(row)

    def render(self):
        """Renders a table in rST format.
        Example:
        +-------+-----+
        | Name  | Age |
        +-------+-----+
        | Alice | 24  |
        |  Bob  | 19  |
        +-------+-----+
        """

        sep = '+'.join('-' * w for w in self._widths)
        sep = f'+{sep}+'

        to_draw = [sep]

        def get_entry(row: Iterable[Sized]):
            elem = '|'.join(f'{e:^{self._widths[i]}}' for i, e in enumerate(row))
            return f'|{elem}|'

        to_draw.append(get_entry(self._columns))
        to_draw.append(sep)

        for row in self._rows:
            to_draw.append(get_entry(row))

        to_draw.append(sep)
        return '\n'.join(to_draw)


class plural:
    def __init__(self, value):
        self.value = value

    def __format__(self, format_spec):
        v = self.value
        singular, sep, plural = format_spec.partition('|')
        plural = plural or f'{singular}s'
        if abs(v) != 1:
            return f'{v} {plural}'
        return f'{v} {singular}'


def human_join(seq, delim=', ', final='or'):
    size = len(seq)
    if size == 0:
        return ''

    if size == 1:
        return seq[0]

    if size == 2:
        return f'{seq[0]} {final} {seq[1]}'

    return delim.join(seq[:-1]) + f' {final} {seq[-1]}'


def format_dt(dt, style=None):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)

    if style is None:
        return f'<t:{int(dt.timestamp())}>'
    return f'<t:{int(dt.timestamp())}:{style}>'
