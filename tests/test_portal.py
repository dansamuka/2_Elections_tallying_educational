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


def test_hierarchy_selects_configured_county_only():
    client = PortalClient(
        "https://forms.example/index.php?r=site%2Findex&p=2&l=2",
        "BANISSA",
        "test",
        constituency_code="040",
        county="MANDERA",
    )
    soup = BeautifulSoup(
        '''<html><body><ul class="breadcrumb"><li>KENYA</li></ul>
        <table><thead><tr><th>County</th><th>Reported</th></tr></thead><tbody>
        <tr id="4" onclick='let id="4"; location.href="/index.php?r=site%2Findex&id=" + id + "&p=2";'><td>KILIFI</td><td>193 of 193</td></tr>
        <tr id="10" onclick='let id="10"; location.href="/index.php?r=site%2Findex&id=" + id + "&p=2";'><td>MANDERA</td><td>81 of 81</td></tr>
        </tbody></table></body></html>''',
        "html.parser",
    )
    urls = client._hierarchy_child_urls(soup, "https://forms.example/index.php?r=site%2Findex&p=2")
    client.close()
    assert urls == ["https://forms.example/index.php?r=site%2Findex&id=10&p=2"]


def test_hierarchy_selects_configured_constituency_inside_county():
    client = PortalClient(
        "https://forms.example/index.php?r=site%2Findex&p=2&l=2",
        "BANISSA",
        "test",
        constituency_code="040",
        county="MANDERA",
    )
    soup = BeautifulSoup(
        '''<html><body><ul class="breadcrumb"><li>KENYA</li><li>MANDERA</li></ul>
        <table><thead><tr><th>Constituency</th><th>Reported</th></tr></thead><tbody>
        <tr id="90" onclick='let id="90"; location.href="/index.php?r=site%2Findex&id=" + id + "&p=2";'><td>BANISSA</td><td>81 of 81</td></tr>
        </tbody></table></body></html>''',
        "html.parser",
    )
    urls = client._hierarchy_child_urls(soup, "https://forms.example/index.php?r=site%2Findex&id=10&p=2")
    client.close()
    assert urls == ["https://forms.example/index.php?r=site%2Findex&id=90&p=2"]


def test_hierarchy_descends_all_rows_after_constituency_breadcrumb():
    client = PortalClient(
        "https://forms.example/index.php?r=site%2Findex&p=2&l=2",
        "BANISSA",
        "test",
        constituency_code="040",
        county="MANDERA",
    )
    soup = BeautifulSoup(
        '''<html><body><ul class="breadcrumb"><li>KENYA</li><li>MANDERA</li><li>BANISSA</li></ul>
        <table><thead><tr><th>Ward</th><th>Reported</th></tr></thead><tbody>
        <tr id="701" onclick='let id="701"; location.href="/index.php?r=site%2Findex&id=" + id + "&p=2";'><td>GUBA</td><td>20 of 20</td></tr>
        <tr id="702" onclick='let id="702"; location.href="/index.php?r=site%2Findex&id=" + id + "&p=2";'><td>MALKAMARI</td><td>17 of 17</td></tr>
        </tbody></table></body></html>''',
        "html.parser",
    )
    urls = client._hierarchy_child_urls(soup, "https://forms.example/index.php?r=site%2Findex&id=90&p=2")
    client.close()
    assert urls == [
        "https://forms.example/index.php?r=site%2Findex&id=701&p=2",
        "https://forms.example/index.php?r=site%2Findex&id=702&p=2",
    ]


def test_leaf_page_prefers_download_icon_and_ignores_preview_and_download_all():
    client = PortalClient(
        "https://forms.example/index.php?r=site%2Findex&p=2&l=2",
        "BANISSA",
        "test",
        constituency_code="040",
        county="MANDERA",
    )
    soup = BeautifulSoup(
        '''<html><body>
        <ul class="breadcrumb"><li>KENYA</li><li>MANDERA</li><li>BANISSA</li><li>GUBA</li><li>GUBA PRIMARY SCHOOL</li></ul>
        <a href="/index.php?r=site%2Fdownload-all&ft=1">Download All</a>
        <table><thead><tr><th>Election/Date</th><th>Polling Station</th><th>Status</th><th>Download</th></tr></thead>
        <tbody><tr><td>27/11/2025 - MNA</td><td>GUBA PRIMARY SCHOOL 01</td><td>Reported</td><td>
        <a href="/index.php?r=site%2Fview&id=abc" title="View"><i class="fa fa-eye"></i></a>
        <a href="/index.php?r=site%2Fdownload&id=abc" title="Download"><i class="fa fa-cloud-download"></i></a>
        </td></tr></tbody></table></body></html>''',
        "html.parser",
    )
    forms = client._extract_form_links(
        soup,
        "https://forms.example/index.php?r=site%2Findex&id=999&p=2",
        constituency_scoped=True,
        include_bulk=False,
    )
    client.close()
    assert len(forms) == 1
    assert "site%2Fdownload&id=abc" in forms[0].source_url
    assert "GUBA PRIMARY SCHOOL 01" in forms[0].source_label


def test_discover_walks_county_constituency_ward_centre_and_leaf(monkeypatch):
    from olkalou_engine.portal import FetchResult

    index_url = "https://forms.example/index.php?r=site%2Findex&p=2&l=2"
    initial_detail = "https://forms.example/index.php?r=site%2Findex&id=90&p=2"
    client = PortalClient(
        index_url,
        "BANISSA",
        "test",
        constituency_code="040",
        detail_url=initial_detail,
        county="MANDERA",
    )
    pages = {
        initial_detail: '''<html><body><ul class="breadcrumb"><li>KENYA</li></ul>
          <table><thead><tr><th>County</th></tr></thead><tbody>
          <tr id="10" onclick='let id="10"; location.href="/index.php?r=site%2Findex&id=" + id + "&p=2";'><td>MANDERA</td></tr>
          </tbody></table></body></html>''',
        "https://forms.example/index.php?r=site%2Findex&id=10&p=2": '''<html><body><ul class="breadcrumb"><li>KENYA</li><li>MANDERA</li></ul>
          <table><thead><tr><th>Constituency</th></tr></thead><tbody>
          <tr id="91" onclick='let id="91"; location.href="/index.php?r=site%2Findex&id=" + id + "&p=2";'><td>BANISSA</td></tr>
          </tbody></table></body></html>''',
        "https://forms.example/index.php?r=site%2Findex&id=91&p=2": '''<html><body><ul class="breadcrumb"><li>KENYA</li><li>MANDERA</li><li>BANISSA</li></ul>
          <table><tbody><tr id="701" onclick='let id="701"; location.href="/index.php?r=site%2Findex&id=" + id + "&p=2";'><td>GUBA</td></tr></tbody></table></body></html>''',
        "https://forms.example/index.php?r=site%2Findex&id=701&p=2": '''<html><body><ul class="breadcrumb"><li>KENYA</li><li>MANDERA</li><li>BANISSA</li><li>GUBA</li></ul>
          <table><tbody><tr id="801" onclick='let id="801"; location.href="/index.php?r=site%2Findex&id=" + id + "&p=2";'><td>GUBA PRIMARY SCHOOL</td></tr></tbody></table></body></html>''',
        "https://forms.example/index.php?r=site%2Findex&id=801&p=2": '''<html><body><ul class="breadcrumb"><li>KENYA</li><li>MANDERA</li><li>BANISSA</li><li>GUBA</li><li>GUBA PRIMARY SCHOOL</li></ul>
          <table><tbody><tr><td>27/11/2025 - MNA</td><td>GUBA PRIMARY SCHOOL 01</td><td>Reported</td><td>
          <a href="/index.php?r=site%2Fview&id=abc">View</a>
          <a href="/index.php?r=site%2Fdownload&id=abc">Download</a>
          </td></tr></tbody></table></body></html>''',
    }

    def fake_get(url, attempts=5):
        body = pages[url].encode()
        return FetchResult(200, body, {"content-type": "text/html"}, url)

    monkeypatch.setattr(client, "get_with_backoff", fake_get)
    forms = client.discover(b"<html><body>BANISSA 81 of 81</body></html>", index_url)
    client.close()
    assert len(forms) == 1
    assert forms[0].source_url.endswith("site%2Fdownload&id=abc")


def test_ol_kalou_current_index_count_is_read() -> None:
    client = PortalClient(
        "https://forms.iebc.or.ke/index.php?r=site%2Findex&p=2&l=2",
        "OL KALOU",
        "test",
        constituency_code="091",
        county="NYANDARUA",
    )
    reported, expected = client.reported_counts(
        b"<html><body>OL KALOU 0 of 144 (0%)</body></html>"
    )
    client.close()
    assert (reported, expected) == (0, 144)


def test_ol_kalou_hierarchy_selects_nyandarua_then_constituency() -> None:
    client = PortalClient(
        "https://forms.example/index.php?r=site%2Findex&p=2&l=2",
        "OL KALOU",
        "test",
        constituency_code="091",
        county="NYANDARUA",
    )
    county_soup = BeautifulSoup(
        '''<html><body><ul class="breadcrumb"><li>KENYA</li></ul>
        <table><thead><tr><th>County</th><th>Reported</th></tr></thead><tbody>
        <tr id="18" onclick='let id="18"; location.href="/index.php?r=site%2Findex&id=" + id + "&p=2";'><td>NYANDARUA</td><td>0 of 144</td></tr>
        <tr id="19" onclick='let id="19"; location.href="/index.php?r=site%2Findex&id=" + id + "&p=2";'><td>NYERI</td><td>0 of 0</td></tr>
        </tbody></table></body></html>''',
        "html.parser",
    )
    assert client._hierarchy_child_urls(
        county_soup, "https://forms.example/index.php?r=site%2Findex&p=2"
    ) == ["https://forms.example/index.php?r=site%2Findex&id=18&p=2"]

    constituency_soup = BeautifulSoup(
        '''<html><body><ul class="breadcrumb"><li>KENYA</li><li>NYANDARUA</li></ul>
        <table><thead><tr><th>Constituency</th><th>Reported</th></tr></thead><tbody>
        <tr id="141" onclick='let id="141"; location.href="/index.php?r=site%2Findex&id=" + id + "&ft=&p=2&es=";'><td>OL KALOU</td><td>0 of 144</td></tr>
        </tbody></table></body></html>''',
        "html.parser",
    )
    assert client._hierarchy_child_urls(
        constituency_soup, "https://forms.example/index.php?r=site%2Findex&id=18&p=2"
    ) == ["https://forms.example/index.php?r=site%2Findex&id=141&ft=&p=2&es="]
    client.close()


def test_ol_kalou_hierarchy_descends_all_five_wards() -> None:
    client = PortalClient(
        "https://forms.example/index.php?r=site%2Findex&p=2&l=2",
        "OL KALOU",
        "test",
        constituency_code="091",
        county="NYANDARUA",
    )
    soup = BeautifulSoup(
        '''<html><body><ul class="breadcrumb"><li>KENYA</li><li>NYANDARUA</li><li>OL KALOU</li></ul>
        <table><thead><tr><th>County Assembly Ward</th><th>Reported</th></tr></thead><tbody>
        <tr id="457" onclick='let id="457"; location.href="/index.php?r=site%2Findex&id=" + id + "&p=2";'><td>RURII</td><td>0 of 33</td></tr>
        <tr id="454" onclick='let id="454"; location.href="/index.php?r=site%2Findex&id=" + id + "&p=2";'><td>KANJUIRI RANGE</td><td>0 of 32</td></tr>
        <tr id="453" onclick='let id="453"; location.href="/index.php?r=site%2Findex&id=" + id + "&p=2";'><td>KARAU</td><td>0 of 27</td></tr>
        <tr id="456" onclick='let id="456"; location.href="/index.php?r=site%2Findex&id=" + id + "&p=2";'><td>KAIMBAGA</td><td>0 of 27</td></tr>
        <tr id="455" onclick='let id="455"; location.href="/index.php?r=site%2Findex&id=" + id + "&p=2";'><td>MIRANGINE</td><td>0 of 25</td></tr>
        </tbody></table></body></html>''',
        "html.parser",
    )
    urls = client._hierarchy_child_urls(
        soup, "https://forms.example/index.php?r=site%2Findex&id=141&p=2"
    )
    client.close()
    assert len(urls) == 5
    assert urls[0].endswith("id=457&p=2")
    assert urls[-1].endswith("id=455&p=2")


def test_ol_kalou_leaf_prefers_individual_cloud_download() -> None:
    client = PortalClient(
        "https://forms.example/index.php?r=site%2Findex&p=2&l=2",
        "OL KALOU",
        "test",
        constituency_code="091",
        county="NYANDARUA",
    )
    soup = BeautifulSoup(
        '''<html><body>
        <ul class="breadcrumb"><li>KENYA</li><li>NYANDARUA</li><li>OL KALOU</li><li>RURII</li><li>EXAMPLE PRIMARY SCHOOL</li></ul>
        <a href="/index.php?r=site%2Fdownload-all&ft=1">Download All</a>
        <table><tbody><tr><td>16/07/2026 - MNA</td><td>EXAMPLE PRIMARY SCHOOL 01</td><td>Reported</td><td>
        <a href="/index.php?r=site%2Fview&id=xyz" title="View"><i class="fa fa-eye"></i></a>
        <a href="/index.php?r=site%2Fdownload&id=xyz" title="Download"><i class="fa fa-cloud-download"></i></a>
        </td></tr></tbody></table></body></html>''',
        "html.parser",
    )
    forms = client._extract_form_links(
        soup,
        "https://forms.example/index.php?r=site%2Findex&id=999&p=2",
        constituency_scoped=True,
        include_bulk=False,
    )
    client.close()
    assert len(forms) == 1
    assert "site%2Fdownload&id=xyz" in forms[0].source_url
    assert forms[0].stream_no == 1


def test_leaf_form_inherits_ward_and_polling_centre_context() -> None:
    from olkalou_engine.portal import CrawlContext

    client = PortalClient(
        "https://forms.example/index.php?r=site%2Findex&p=2&l=2",
        "MALAVA",
        "test",
        constituency_code="201",
        county="KAKAMEGA",
    )
    soup = BeautifulSoup(
        '''<html><body><ul class="breadcrumb"><li>KAKAMEGA</li><li>MALAVA</li><li>WEST KABRAS</li><li>MUTSUMA PRIMARY SCHOOL</li></ul>
        <table><tr><td>037201100200101</td><td>MUTSUMA PRIMARY SCHOOL 01</td><td><a href="/index.php?r=site%2Fdownload&id=1675">Download</a></td></tr></table>
        </body></html>''',
        "html.parser",
    )
    forms = client._extract_form_links(
        soup,
        "https://forms.example/index.php?r=site%2Findex&id=100&p=2",
        constituency_scoped=True,
        context=CrawlContext(
            county_name="KAKAMEGA",
            constituency_name="MALAVA",
            ward_name="WEST KABRAS",
            ward_code="1002",
            polling_centre_name="MUTSUMA PRIMARY SCHOOL",
            polling_centre_code="001",
            hierarchy_path=("KAKAMEGA", "MALAVA", "WEST KABRAS", "MUTSUMA PRIMARY SCHOOL"),
        ),
    )
    client.close()
    assert len(forms) == 1
    assert forms[0].ward_name == "WEST KABRAS"
    assert forms[0].ward_code == "1002"
    assert forms[0].polling_centre_name == "MUTSUMA PRIMARY SCHOOL"
    assert forms[0].polling_centre_code == "001"
