# Malava OCR benchmark

Malava is configured as an accuracy-validation dataset, not a constituency tally.

1. Run the historical sync/OCR workflow.
2. Open the Malava archive workbench.
3. Compare every OCR field against the Form 35A image.
4. Correct errors, enter the reviewer name and save the benchmark row.
5. Download the confirmed OCR benchmark truth CSV.
6. Run:

```bash
python scripts/measure_historical_ocr_accuracy.py malava-2025 path/to/malava-2025-ocr-benchmark-truth.csv
```

The report separates field coverage from exact accuracy and mean absolute error. Candidate V01 remains `NOT_RUN` until the complete legal candidate roster and ballot order have been certified.
