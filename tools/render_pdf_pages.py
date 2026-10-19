from __future__ import annotations

import argparse
from pathlib import Path

import pypdfium2 as pdfium


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("output_dir")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    document = pdfium.PdfDocument(args.pdf)
    for index in range(len(document)):
        page = document[index]
        bitmap = page.render(scale=2.0, rotation=0)
        image = bitmap.to_pil()
        image.save(output / f"page-{index + 1}.png")
    print(len(document))


if __name__ == "__main__":
    main()
