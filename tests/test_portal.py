from bs4 import BeautifulSoup

from olkalou_engine.portal import PortalClient, infer_stream_identity


def test_infer_stream_identity():
    key, stream = infer_stream_identity("Ol Kalou 018091045704801 Form 35A")
    assert stream == 1
    assert key is not None and key.endswith("-01")


def test_extract_form_link():
    client = PortalClient("https://forms.example/index", "OL KALOU", "test")
    soup = BeautifulSoup(
        '<html><body><a href="/forms/018091045704801.pdf">OL KALOU Form 35A Rurii Primary</a></body></html>',
        "html.parser",
    )
    forms = client._extract_form_links(soup, "https://forms.example/index")
    client.close()
    assert len(forms) == 1
    assert forms[0].form_type == "35A"


def test_infer_stream_identity_for_historical_constituency():
    key, stream = infer_stream_identity("Banissa 009040001101801 Form 35A", "040")
    assert key is not None
    assert key.startswith("040-")
    assert stream == 1


def test_extract_form_link_from_yii_data_url_attribute():
    client = PortalClient("https://forms.example/index", "BANISSA", "test", constituency_code="040")
    soup = BeautifulSoup(
        '''<html><body><table><tr><td>BANISSA</td><td><button data-url="/index.php?r=site/download-form&id=123&name=35A">Download Form 35A</button></td></tr></table></body></html>''',
        "html.parser",
    )
    forms = client._extract_form_links(soup, "https://forms.example/index")
    client.close()
    assert len(forms) == 1
    assert forms[0].source_url.startswith("https://forms.example/index.php")
    assert forms[0].form_type == "35A"


def test_constituency_detail_url_from_clickable_table_row():
    client = PortalClient("https://forms.example/index", "BANISSA", "test", constituency_code="040")
    soup = BeautifulSoup(
        '''<table><tr data-url="/index.php?r=site/constituency&id=40"><td>BANISSA</td><td>81 of 81</td></tr></table>''',
        "html.parser",
    )
    urls = client._constituency_detail_urls(soup, "https://forms.example/index")
    client.close()
    assert urls == ["https://forms.example/index.php?r=site/constituency&id=40"]


def test_reported_counts_for_constituency_row():
    client = PortalClient("https://forms.example/index", "BANISSA", "test", constituency_code="040")
    reported, expected = client.reported_counts(b"<html><body>BANISSA 81 of 81 (100%)</body></html>")
    client.close()
    assert (reported, expected) == (81, 81)


def test_pagination_links_are_collected_from_yii_pager():
    client = PortalClient("https://forms.example/index", "BANISSA", "test", constituency_code="040")
    soup = BeautifulSoup(
        '<ul class="pagination"><li><a href="/index.php?r=site/forms&page=2">2</a></li><li><a rel="next" href="/index.php?r=site/forms&page=3">Next</a></li></ul>',
        "html.parser",
    )
    urls = client._pagination_urls(soup, "https://forms.example/index.php?r=site/forms&page=1")
    client.close()
    assert urls == [
        "https://forms.example/index.php?r=site/forms&page=2",
        "https://forms.example/index.php?r=site/forms&page=3",
    ]


def test_constituency_scoped_detail_accepts_generic_download_links():
    client = PortalClient("https://forms.example/index", "BANISSA", "test", constituency_code="040")
    soup = BeautifulSoup(
        '<table><tr><td>001101801</td><td>Township Primary</td><td><a href="/index.php?r=site/download&id=123">Download</a></td></tr></table>',
        "html.parser",
    )
    forms = client._extract_form_links(
        soup, "https://forms.example/index.php?r=site/constituency&id=40", constituency_scoped=True
    )
    client.close()
    assert len(forms) == 1
    assert forms[0].form_type == "35A"


def test_global_download_all_is_not_treated_as_a_constituency_form():
    client = PortalClient("https://forms.example/index", "BANISSA", "test", constituency_code="040")
    soup = BeautifulSoup(
        '<html><body>BANISSA 81 of 81 <a href="/index.php?r=site/download-all">Download All</a></body></html>',
        "html.parser",
    )
    forms = client._extract_form_links(soup, "https://forms.example/index")
    client.close()
    assert forms == []


def test_current_iebc_javascript_row_url_is_reconstructed_with_row_id():
    client = PortalClient(
        "https://forms.iebc.or.ke/index.php?r=site%2Findex&p=2&l=2",
        "BANISSA",
        "test",
        constituency_code="040",
    )
    soup = BeautifulSoup(
        '''<table><tr id="90" onclick='\n            let id = "90";\n            location.href = "/index.php?r=site%2Findex&amp;id=" + id + "&amp;ft=" + "" + "&amp;p=2"+ "&amp;es=";\n        '><td>BANISSA</td><td>81 of 81 (100%)</td></tr></table>''',
        "html.parser",
    )
    urls = client._constituency_detail_urls(
        soup, "https://forms.iebc.or.ke/index.php?r=site%2Findex&p=2&l=2"
    )
    client.close()
    assert urls == [
        "https://forms.iebc.or.ke/index.php?r=site%2Findex&id=90&ft=&p=2&es="
    ]


def test_detail_redirect_back_to_national_index_is_rejected(monkeypatch):
    client = PortalClient(
        "https://forms.example/index.php?r=site%2Findex&p=2&l=2",
        "BANISSA",
        "test",
        constituency_code="040",
        detail_url="https://forms.example/index.php?r=site%2Findex&id=90&p=2",
    )

    def fake_get(url, attempts=5):
        from olkalou_engine.portal import FetchResult

        return FetchResult(
            200,
            b'<html><body>BANISSA 81 of 81 <a href="/download-all">Download All</a></body></html>',
            {"content-type": "text/html"},
            "https://forms.example/index.php?r=site%2Findex&p=2&l=2",
        )

    monkeypatch.setattr(client, "get_with_backoff", fake_get)
    try:
        client.discover(b"<html><body>BANISSA 81 of 81</body></html>")
        raise AssertionError("redirect to national index should be rejected")
    except RuntimeError as exc:
        assert "lost its row id" in str(exc)
    finally:
        client.close()
