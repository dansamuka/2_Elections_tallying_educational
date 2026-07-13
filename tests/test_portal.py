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
