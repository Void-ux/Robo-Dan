from __future__ import annotations
from typing import TypedDict, Any

from typing_extensions import NotRequired

__all__ = (
    'PartialEpisodePayload',
    'EpisodePayload',
    'ImagePayload',
    'SeasonPayload',
    'SeriesPayload',
    'EpisodeFilePayload'
)


class PartialEpisodePayload(TypedDict):
    seriesId: int
    tvdbId: int
    episodeFileId: int
    seasonNumber: int
    episodeNumber: int
    title: str
    airDate: str
    airDateUtc: str
    overview: str
    hasFile: bool
    monitored: bool
    absoluteEpisodeNumber: int
    unverifiedSceneNumbering: bool
    images: NotRequired[list[dict[str, str]]]
    id: int


class PartialEpisodePayload_(PartialEpisodePayload):
    images: list[dict[str, str]]


class EpisodePayload(PartialEpisodePayload):    
    series: SeriesPayload
    seasons: list[SeasonPayload]
    images: list[dict[str, str]]


class ImagePayload(TypedDict):
    coverType: str
    url: str
    remoteUrl: str


class SeasonPayload(TypedDict):
    seasonNumber: int
    monitored: bool
    statistics: NotRequired[dict[str, Any]]


class SeriesPayload(TypedDict):
    title: str
    alternateTitles: list[dict[str, str]]
    sortTitle: str
    status: str
    ended: bool
    overview: str
    previousAiring: str
    network: str
    airTime: str
    images: list[ImagePayload]
    seasons: list[SeasonPayload]
    year: int
    path: str
    qualityProfileId: int
    languageProfileId: int
    seasonFolder: bool
    monitored: bool
    useSceneNumbering: bool
    runtime: int
    tvdbId: int
    tvRageId: int
    tvMazeId: int
    firstAired: NotRequired[str]
    seriesType: str
    cleanTitle: str
    imdbId: str
    titleSlug: str
    rootFolderPath: str
    genres: list[str]
    tags: list
    added: str
    ratings: dict[str, int]
    statistics: NotRequired[dict[str, Any]]
    id: int


class EpisodeFilePayload(TypedDict):
    seriesId: int
    seasonNumber: int
    relativePath: str
    path: str
    size: int
    dateAdded: str
    language: dict[str, str]
    quality: dict[str, Any]
    mediaInfo: dict[str, Any]
    qualityCutoffNotMet: bool
    languageCutoffNotMet: bool
    id: int