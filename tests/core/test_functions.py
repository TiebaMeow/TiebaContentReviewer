from unittest.mock import MagicMock

import pytest

from src.functions import has_url, keyword_count, text_length


@pytest.fixture
def mock_data():
    data = MagicMock()
    # Mock text and full_text attrs
    data.text = "hello world"
    data.full_text = "hello world full"
    return data


def test_text_length(mock_data):
    assert text_length(mock_data) == 11

    mock_data.text = ""
    assert text_length(mock_data) == 0


def test_keyword_count(mock_data):
    mock_data.full_text = "aa bb aa cc"
    assert keyword_count(mock_data, ["aa"]) == 2
    assert keyword_count(mock_data, ["aa", "bb"]) == 3
    assert keyword_count(mock_data, ["dd"]) == 0


def test_has_url(mock_data):
    mock_data.full_text = "Visit http://example.com"
    assert has_url(mock_data) is True

    mock_data.full_text = "Visit https://google.com/test"
    assert has_url(mock_data) is True

    mock_data.full_text = "No url here"
    assert has_url(mock_data) is False
