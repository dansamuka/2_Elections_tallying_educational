# Banissa source documents

Place every Banissa election source PDF or image in this folder. Nested folders are supported.

Accepted formats: PDF, PNG, JPG/JPEG, TIFF and WebP.

The OCR command inventories every file recursively, collapses exact duplicates by SHA-256, copies an immutable public mirror into `data/public/elections/banissa-2025/forms/uploaded/`, classifies Form 35A and Form 35B pages, matches Form 35As to the certified 81-stream register, and creates `../ocr/review_queue.csv`.

OCR never publishes a stream tally. Reviewers must independently confirm the pre-filled values and import the completed review CSV through the existing `archive-import` command.
