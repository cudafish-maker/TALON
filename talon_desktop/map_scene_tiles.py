"""Qt scene helpers for efficient raster map tile rendering."""
from __future__ import annotations

import collections
import logging
import typing

from PySide6 import QtCore, QtGui, QtNetwork, QtWidgets

from talon_desktop.map_tiles import TileRequest


class TilePixmapCache:
    """Small GUI-thread LRU cache for decoded map tile pixmaps."""

    def __init__(self, max_entries: int = 384) -> None:
        self._max_entries = max_entries
        self._pixmaps: collections.OrderedDict[str, QtGui.QPixmap] = (
            collections.OrderedDict()
        )

    def get(self, url: str) -> QtGui.QPixmap | None:
        pixmap = self._pixmaps.get(url)
        if pixmap is None:
            return None
        if pixmap.isNull():
            self._pixmaps.pop(url, None)
            return None
        self._pixmaps.move_to_end(url)
        return pixmap

    def put(self, url: str, pixmap: QtGui.QPixmap) -> None:
        if pixmap.isNull():
            return
        self._pixmaps[url] = QtGui.QPixmap(pixmap)
        self._pixmaps.move_to_end(url)
        while len(self._pixmaps) > self._max_entries:
            self._pixmaps.popitem(last=False)


SHARED_TILE_PIXMAP_CACHE = TilePixmapCache()


class MapTileSceneRenderer(QtCore.QObject):
    """Manage tile item reuse, stale-frame coverage, and async tile loading."""

    def __init__(
        self,
        *,
        scene: QtWidgets.QGraphicsScene,
        network: QtNetwork.QNetworkAccessManager,
        user_agent: str,
        logger: logging.Logger,
        cache: TilePixmapCache = SHARED_TILE_PIXMAP_CACHE,
    ) -> None:
        super().__init__(scene)
        self._scene = scene
        self._network = network
        self._user_agent = user_agent
        self._log = logger
        self._cache = cache
        self._generation = 0
        self._tile_items: list[QtWidgets.QGraphicsPixmapItem] = []
        self._stale_tile_items: list[QtWidgets.QGraphicsPixmapItem] = []
        self._active_replies: list[QtNetwork.QNetworkReply] = []
        self._pending_tile_count = 0
        self._finished_tile_count = 0
        self._max_stale_items = 216

    @property
    def generation(self) -> int:
        return self._generation

    def begin_frame(self) -> int:
        self._generation += 1
        self._abort_active_replies()
        self._promote_current_tiles_to_stale()
        self._remove_non_stale_items()
        self._pending_tile_count = 0
        self._finished_tile_count = 0
        return self._generation

    def request_tiles(self, tiles: typing.Iterable[TileRequest]) -> None:
        requests = tuple(tiles)
        generation = self._generation
        self._pending_tile_count = len(requests)
        self._finished_tile_count = 0
        if not requests:
            self._discard_stale_tiles()
            return
        for tile in requests:
            pixmap = self._cache.get(tile.url)
            if pixmap is not None:
                self._add_tile_pixmap(tile, pixmap, generation)
                self._mark_tile_finished(generation)
                continue
            self._request_tile(tile, generation)

    def _promote_current_tiles_to_stale(self) -> None:
        self._stale_tile_items.extend(
            item for item in self._tile_items
            if item.scene() is self._scene
        )
        self._tile_items = []
        for item in self._stale_tile_items:
            item.setZValue(-25)
        while len(self._stale_tile_items) > self._max_stale_items:
            item = self._stale_tile_items.pop(0)
            if item.scene() is self._scene:
                self._scene.removeItem(item)

    def _remove_non_stale_items(self) -> None:
        stale_ids = {id(item) for item in self._stale_tile_items}
        for item in list(self._scene.items()):
            if id(item) not in stale_ids:
                self._scene.removeItem(item)

    def _discard_stale_tiles(self) -> None:
        for item in self._stale_tile_items:
            if item.scene() is self._scene:
                self._scene.removeItem(item)
        self._stale_tile_items = []

    def _request_tile(self, tile: TileRequest, generation: int) -> None:
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(tile.url))
        request.setHeader(QtNetwork.QNetworkRequest.UserAgentHeader, self._user_agent)
        request.setAttribute(
            QtNetwork.QNetworkRequest.CacheLoadControlAttribute,
            QtNetwork.QNetworkRequest.PreferCache,
        )
        reply = self._network.get(request)
        self._active_replies.append(reply)
        reply.finished.connect(
            lambda reply=reply, tile=tile, generation=generation: self._tile_finished(
                reply,
                tile,
                generation,
            )
        )

    def _tile_finished(
        self,
        reply: QtNetwork.QNetworkReply,
        tile: TileRequest,
        generation: int,
    ) -> None:
        try:
            if reply in self._active_replies:
                self._active_replies.remove(reply)
            if reply.error() != QtNetwork.QNetworkReply.NoError:
                if generation == self._generation:
                    self._log.debug("Map tile request failed: %s", reply.errorString())
                return
            pixmap = QtGui.QPixmap()
            if not pixmap.loadFromData(reply.readAll()):
                return
            self._cache.put(tile.url, pixmap)
            if generation == self._generation:
                self._add_tile_pixmap(tile, pixmap, generation)
        finally:
            if generation == self._generation:
                self._mark_tile_finished(generation)
            reply.deleteLater()

    def _add_tile_pixmap(
        self,
        tile: TileRequest,
        pixmap: QtGui.QPixmap,
        generation: int,
    ) -> None:
        if generation != self._generation or pixmap.isNull():
            return
        item = self._scene.addPixmap(pixmap)
        item.setTransformationMode(QtCore.Qt.SmoothTransformation)
        item.setCacheMode(QtWidgets.QGraphicsItem.DeviceCoordinateCache)
        item.setAcceptedMouseButtons(QtCore.Qt.NoButton)
        item.setPos(tile.scene_x, tile.scene_y)
        item.setTransform(
            QtGui.QTransform().scale(
                tile.scene_width / pixmap.width(),
                tile.scene_height / pixmap.height(),
            )
        )
        item.setZValue(-20)
        self._tile_items.append(item)

    def _mark_tile_finished(self, generation: int) -> None:
        if generation != self._generation:
            return
        self._finished_tile_count += 1
        if (
            self._finished_tile_count >= self._pending_tile_count
            and len(self._tile_items) >= self._pending_tile_count
        ):
            self._discard_stale_tiles()

    def _abort_active_replies(self) -> None:
        replies = list(self._active_replies)
        self._active_replies.clear()
        for reply in replies:
            if reply.isRunning():
                reply.abort()
