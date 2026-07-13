from olkalou_engine.ocr.words import words_to_int


def test_words_to_int():
    assert words_to_int("Two hundred and one votes") == 201
    assert words_to_int("one thousand and forty two") == 1042
