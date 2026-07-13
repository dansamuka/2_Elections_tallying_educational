from olkalou_engine.ocr.cloud import OCRValue, merge_engine_outputs, numeric_value


def test_numeric_value_strips_commas_and_noise():
    assert numeric_value(" 1,204 votes ") == 1204
    assert numeric_value("illegible") is None


def test_dual_engine_and_words_consensus():
    roi = {
        "fields": {
            "candidate_UDA.numeral": [0, 0, 1, 1],
            "candidate_UDA.words": [0, 0, 1, 1],
        }
    }
    outputs = {
        "gcv": {
            "candidate_UDA.numeral": OCRValue("201", 0.99),
            "candidate_UDA.words": OCRValue("two hundred and one", 0.98),
        },
        "textract": {
            "candidate_UDA.numeral": OCRValue("201", 0.97),
            "candidate_UDA.words": OCRValue("two hundred and one", 0.96),
        },
    }
    field = merge_engine_outputs(outputs, roi)["candidate_UDA"]
    assert field.value == 201
    assert field.words_value == 201
    assert field.consensus is True
    assert field.confidence == 0.97


def test_engine_disagreement_returns_no_value():
    roi = {"fields": {"rejected.numeral": [0, 0, 1, 1]}}
    outputs = {
        "gcv": {"rejected.numeral": OCRValue("5", 0.99)},
        "textract": {"rejected.numeral": OCRValue("8", 0.99)},
    }
    field = merge_engine_outputs(outputs, roi)["rejected"]
    assert field.value is None
    assert field.consensus is False
