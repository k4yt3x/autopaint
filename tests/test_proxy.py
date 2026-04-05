from unittest.mock import MagicMock, patch

from autopaint.proxy import fetch_proxies

SAMPLE_RELAYS = {
    "wireguard": {
        "relays": [
            {"location": "ca-mtr", "active": True, "hostname": "ca-mtr-wg-001"},
            {"location": "ca-tor", "active": True, "hostname": "ca-tor-wg-002"},
            {"location": "ca-van", "active": False, "hostname": "ca-van-wg-003"},
            {"location": "us-nyc", "active": True, "hostname": "us-nyc-wg-001"},
            {"location": "us-lax", "active": True, "hostname": "us-lax-wg-002"},
            {"location": "gb-lon", "active": True, "hostname": "gb-lon-wg-001"},
        ]
    }
}


class TestFetchProxies:
    @patch("autopaint.proxy.requests.get")
    def test_single_country(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = SAMPLE_RELAYS
        mock_get.return_value = mock_resp

        proxies = fetch_proxies(["ca"])

        # ca-van is inactive, so only 2
        assert len(proxies) == 2
        assert "socks5://ca-mtr-wg-socks5-001.relays.mullvad.net:1080" in proxies
        assert "socks5://ca-tor-wg-socks5-002.relays.mullvad.net:1080" in proxies

    @patch("autopaint.proxy.requests.get")
    def test_multiple_countries(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = SAMPLE_RELAYS
        mock_get.return_value = mock_resp

        proxies = fetch_proxies(["ca", "us"])

        # 2 active CA + 2 active US = 4
        assert len(proxies) == 4

    @patch("autopaint.proxy.requests.get")
    def test_no_matching_country(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = SAMPLE_RELAYS
        mock_get.return_value = mock_resp

        proxies = fetch_proxies(["jp"])
        assert proxies == []

    @patch("autopaint.proxy.requests.get")
    def test_inactive_relays_excluded(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = SAMPLE_RELAYS
        mock_get.return_value = mock_resp

        proxies = fetch_proxies(["ca"])
        hostnames = [p for p in proxies if "ca-van" in p]
        assert hostnames == []

    @patch("autopaint.proxy.requests.get")
    def test_hostname_transformation(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = SAMPLE_RELAYS
        mock_get.return_value = mock_resp

        proxies = fetch_proxies(["gb"])

        assert len(proxies) == 1
        assert proxies[0] == "socks5://gb-lon-wg-socks5-001.relays.mullvad.net:1080"

    @patch("autopaint.proxy.requests.get")
    def test_network_error_propagates(self, mock_get):
        import requests

        mock_get.side_effect = requests.ConnectionError()

        try:
            fetch_proxies(["ca"])
            assert False, "Should have raised"
        except requests.ConnectionError:
            pass
