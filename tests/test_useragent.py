from unittest.mock import MagicMock, patch

from autopaint.useragent import (
    _is_mobile,
    _parse_chrome_version,
    _parse_platform,
    build_extra_headers,
    fetch_user_agents,
)


# ---------------------------------------------------------------------------
# _parse_chrome_version
# ---------------------------------------------------------------------------


class TestParseChromeVersion:
    def test_chrome_linux(self):
        ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
        assert _parse_chrome_version(ua) == 146

    def test_chrome_windows(self):
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        assert _parse_chrome_version(ua) == 136

    def test_firefox_returns_none(self):
        ua = "Mozilla/5.0 (X11; Linux x86_64; rv:149.0) Gecko/20100101 Firefox/149.0"
        assert _parse_chrome_version(ua) is None

    def test_edge_excluded(self):
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0"
        assert _parse_chrome_version(ua) is None

    def test_opera_excluded(self):
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/146.0.0.0 OPR/100.0.0.0"
        assert _parse_chrome_version(ua) is None

    def test_no_version_returns_none(self):
        assert _parse_chrome_version("SomeRandomBot/1.0") is None


# ---------------------------------------------------------------------------
# _parse_platform
# ---------------------------------------------------------------------------


class TestParsePlatform:
    def test_windows(self):
        assert _parse_platform("Mozilla/5.0 (Windows NT 10.0)") == '"Windows"'

    def test_macos(self):
        assert _parse_platform("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)") == '"macOS"'

    def test_android(self):
        assert _parse_platform("Mozilla/5.0 (Linux; Android 14)") == '"Android"'

    def test_chromeos(self):
        assert _parse_platform("Mozilla/5.0 (X11; CrOS x86_64 14541.0.0)") == '"Chrome OS"'

    def test_linux_default(self):
        assert _parse_platform("Mozilla/5.0 (X11; Linux x86_64)") == '"Linux"'

    def test_unknown_falls_to_linux(self):
        assert _parse_platform("SomeBot/1.0") == '"Linux"'


# ---------------------------------------------------------------------------
# _is_mobile
# ---------------------------------------------------------------------------


class TestIsMobile:
    def test_mobile_keyword(self):
        assert _is_mobile("Chrome/146.0 Mobile Safari/537.36") is True

    def test_android_keyword(self):
        assert _is_mobile("Mozilla/5.0 (Linux; Android 14)") is True

    def test_desktop(self):
        assert _is_mobile("Mozilla/5.0 (X11; Linux x86_64) Chrome/146.0") is False


# ---------------------------------------------------------------------------
# build_extra_headers
# ---------------------------------------------------------------------------


class TestBuildExtraHeaders:
    def test_chrome_returns_sec_ch_ua(self):
        ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
        headers = build_extra_headers(ua)

        assert "sec-ch-ua" in headers
        assert "Chromium" in headers["sec-ch-ua"]
        assert "146" in headers["sec-ch-ua"]
        assert headers["sec-ch-ua-mobile"] == "?0"
        assert headers["sec-ch-ua-platform"] == '"Linux"'
        assert headers["DNT"] == "1"
        assert headers["Priority"] == "u=1, i"

    def test_chrome_windows_platform(self):
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        headers = build_extra_headers(ua)
        assert headers["sec-ch-ua-platform"] == '"Windows"'

    def test_chrome_android_mobile(self):
        ua = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/146.0.6478.71 Mobile Safari/537.36"
        headers = build_extra_headers(ua)
        assert headers["sec-ch-ua-mobile"] == "?1"
        assert headers["sec-ch-ua-platform"] == '"Android"'

    def test_firefox_returns_firefox_headers(self):
        ua = "Mozilla/5.0 (X11; Linux x86_64; rv:149.0) Gecko/20100101 Firefox/149.0"
        headers = build_extra_headers(ua)

        assert headers["Sec-GPC"] == "1"
        assert headers["Priority"] == "u=0"
        assert headers["TE"] == "trailers"
        assert "sec-ch-ua" not in headers
        assert "DNT" not in headers

    def test_edge_treated_as_firefox(self):
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/146.0.0.0 Edg/146.0.0.0"
        headers = build_extra_headers(ua)
        assert "Sec-GPC" in headers
        assert "sec-ch-ua" not in headers


# ---------------------------------------------------------------------------
# fetch_user_agents
# ---------------------------------------------------------------------------


class TestFetchUserAgents:
    @patch("autopaint.useragent.requests.get")
    def test_returns_stripped_lines(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = "UA-One\nUA-Two\n\nUA-Three\n"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        agents = fetch_user_agents()

        assert agents == ["UA-One", "UA-Two", "UA-Three"]
        mock_get.assert_called_once()

    @patch("autopaint.useragent.requests.get")
    def test_empty_response(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = ""
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        assert fetch_user_agents() == []

    @patch("autopaint.useragent.requests.get")
    def test_network_error_propagates(self, mock_get):
        import requests

        mock_get.side_effect = requests.ConnectionError("DNS failure")

        try:
            fetch_user_agents()
            assert False, "Should have raised"
        except requests.ConnectionError:
            pass
