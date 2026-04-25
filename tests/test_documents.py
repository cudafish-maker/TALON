"""Tests for document upload hardening."""

import sys
import types

import pytest

from talon.documents import DocumentBlockedExtension, _sanitize_image


def test_sanitize_image_fails_closed_when_pillow_reencode_fails(monkeypatch):
    fake_pil = types.ModuleType("PIL")

    class FakeImage:
        @staticmethod
        def open(_data):
            raise OSError("bad image")

    fake_pil.Image = FakeImage
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)
    monkeypatch.setitem(sys.modules, "PIL.Image", FakeImage)

    with pytest.raises(DocumentBlockedExtension):
        _sanitize_image(b"not really an image", "image/png")
