import logging
from typing import Any, Literal, overload
from urllib.parse import quote as _uriquote

import aiohttp
from yarl import URL

from .models.sonarr import PartialEpisodePayload_, SeriesPayload, EpisodePayload, PartialEpisodePayload, EpisodeFilePayload

log = logging.getLogger(__name__)


class Route:
    """A helper class for instantiating a HTTP method to Sonarr

    Parameters
    -----------
    method: :class:`str`
        The HTTP method you wish to perform, e.g. ``"POST"``
    path: :class:`str`
        The prepended path to the API endpoint you with to target.
    parameters: Any
        This is a special cased kwargs. Anything passed to these will substitute it's key to value in the `path`.
    """

    def __init__(
        self,
        method: Literal['GET', 'POST', 'PUT', 'DELETE'],
        path: str,
        *,
        protocol: Literal['http', 'https'],
        host: str,
        port: int,
        **parameters: Any
    ) -> None:
        self.method = method
        self.path = path
        self.protocol = protocol
        self.host = host
        self.port = port
        self.parameters = parameters

        url = f'{protocol}://{host}:{port}' + self.path
        if parameters:
            url = url.format_map({k: _uriquote(v) if isinstance(v, str) else v for k, v in self.parameters.items()})

        self.url: URL = URL(url, encoded=True)


class Client:
    def __init__(
        self,
        api_key: str,
        *,
        host: str = 'localhost',
        port: int = 8989,
        protocol: Literal['http', 'https'] = 'http',
        session: aiohttp.ClientSession | None = None
    ):
        self.api_key = api_key
        self.host = host
        self.port = port
        self.protocol: Literal['http', 'https'] = protocol
        self.session = session

    async def _generate_session(self) -> aiohttp.ClientSession:
        # this needs to be done in an async context
        return aiohttp.ClientSession()

    async def request(self, route: Route, **kwargs) -> Any:
        if self.session is None:
            self.session = await self._generate_session()

        headers = kwargs.pop('headers', {})
        headers['X-Api-Key'] = self.api_key

        params = kwargs.pop('params', {})
        params['apikey'] = self.api_key

        async with self.session.request(route.method, route.url, params=params, headers=headers, **kwargs) as response:
            log.debug('%s %s with %s has returned %s', route.method, route.url, params, response.status)
            response.raise_for_status()
            content = await response.json()

        return content

    async def look_up_series(self, search_phrase: str) -> list[SeriesPayload]:
        route = Route(
            'GET',
            '/api/v3/series/lookup',
            protocol=self.protocol,
            host=self.host,
            port=self.port
        )
        params = {
            'term': search_phrase
        }

        return await self.request(route, params=params)

    async def get_series(self, tvdb_id: int, *, include_season_images: bool = False) -> SeriesPayload | None:
        """Obtains a single locally stored Sonarr series through its TVDB ID."""

        route = Route(
            'GET',
            '/api/v3/series',
            protocol=self.protocol,
            host=self.host,
            port=self.port
        )
        params = {
            'tvdbId': tvdb_id,
            'includeSeasonImages': str(include_season_images).lower(),
        }

        return await self.request(route, params=params)

    @overload
    async def get_episodes(self, series_id: int, season: int | None, episode_range: range | None, *, include_images: Literal[True]) -> list[PartialEpisodePayload_]:
        ...

    @overload
    async def get_episodes(self, series_id: int, season: int | None, episode_range: range | None, *, include_images: Literal[False]) -> list[PartialEpisodePayload]:
        ...

    @overload
    async def get_episodes(self, series_id: int, season: int | None, episode_range: range | None) -> list[PartialEpisodePayload]:
        ...


    async def get_episodes(
        self,
        series_id: int,
        season: int | None,
        episode_range: range | None,
        *,
        include_images: bool = False
    ) -> list[PartialEpisodePayload] | list[PartialEpisodePayload_]:
        """Gets Sonarr's episode IDs for a series.

        Parameters
        ----------
        series_id: int
            Sonarr's local series ID assigned to the series. Obtained through `get_series`.
        season: int | None
            The series' season number.
        episode_range: range
            The range of episodes to include.
        include_images: bool
            Whether or not to include the episode's artwork.
        """
        route = Route(
            'GET',
            '/api/v3/episode',
            protocol=self.protocol,
            host=self.host,
            port=self.port
        )
        # technically there is support for getting a specific season
        # though this doesn't work, so we'll manually filter everything
        params = {
            'seriesId': series_id,
            'includeImages': str(include_images).lower(),
        }

        content = await self.request(route, params=params)
        episodes = filter(lambda x: x['seasonNumber'] == season and x['episodeNumber'] in episode_range, content)
        return list(episodes)

    async def get_episode(self, episode_id: int) -> EpisodePayload:
        route = Route(
            'GET',
            '/api/v3/episode/{id}',
            id=episode_id,
            protocol=self.protocol,
            host=self.host,
            port=self.port
        )

        return await self.request(route)

    async def get_episode_file(self, episode_file_id: int) -> EpisodeFilePayload:
        route = Route(
            'GET',
            '/api/v3/episodefile/{id}',
            id=episode_file_id,
            protocol=self.protocol,
            host=self.host,
            port=self.port
        )

        return await self.request(route)

    async def add_series(
        self,
        tvdb_id: int,
        quality_profile_id: int,
        root_dir: str,
        season_folder: bool = True,
        monitored: bool = True,
        search_for_missing_episodes: bool = False
    ) -> dict[str, Any]:
        # TODO make it possible to pass in an already looked up value
        series: dict[Any, Any] = (await self.look_up_series(f'tvdb:{tvdb_id}'))[0]  # type: ignore
        series.update({
            "added": "0001-01-01T00:00:00Z",
            "rootFolderPath": root_dir,
            "languageProfileId": 1,

            'qualityProfileId': quality_profile_id,
            'seasonFolder': season_folder,
            'monitored': monitored,
            'useSceneNumbering': False,
            'addOptions': {
                'monitor': 'all',
                'searchForMissingEpisodes': search_for_missing_episodes,
                'searchForCutoffUnmetEpisodes': False
            }
        })
        route = Route(
            'POST',
            '/api/v3/series',
            protocol=self.protocol,
            host=self.host,
            port=self.port
        )
        headers = {
            'accept': 'application/json',
            'Content-Type': 'application/json'
        }

        return await self.request(route, json=series, headers=headers)

    async def download_episodes(self, episodes: list[int]) -> dict:
        route = Route(
            'POST',
            '/api/v3/command',
            protocol=self.protocol,
            host=self.host,
            port=self.port,
        )
        data = {
            'episodeIds': episodes,
            'name': 'EpisodeSearch'
        }
        headers = {
            'accept': 'application/json',
            'Content-Type': 'application/json'
        }

        return await self.request(route, json=data, headers=headers)

    async def delete_episode(self, episode_file: EpisodeFilePayload) -> None:
        route = Route(
            'DELETE',
            '/api/v3/episodefile/{id}',
            id=episode_file['id'],
            protocol=self.protocol,
            host=self.host,
            port=self.port
        )

        await self.request(route)
