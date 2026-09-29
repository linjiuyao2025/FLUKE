# OFD integration

The desktop converter uses the Apache-2.0 OFDRW 2.4.0 converter through a small Java command-line bridge. Two small compatibility sources derived from OFDRW 2.4.0 are included with their upstream notices; details are in `THIRD-PARTY-NOTICES.md`.

The bridge currently exports OFD to HTML, plain text, and a ZIP of page PNGs. PDF output uses those OFDRW-rendered PNG pages with Qt's PDF writer, so the text is not searchable or editable. The package excludes iText and does not call OFDRW's built-in PDF exporters. PDFBox remains in the runtime because OFDRW's AWT renderer uses its image blend-mode classes. Text extraction can miss text represented as glyph indices, paths, or page images.

To build the local engine on Windows, run `scripts/build-ofd-engine.ps1`. It downloads the pinned Temurin JDK archive, verifies its SHA-256, verifies the Apache Maven distribution using its published SHA-512, builds the Java bridge, and creates a small bundled Java runtime. Build output is placed in the ignored `engine/ofd/build` directory; downloaded developer tools and Maven dependencies stay under `qa-sandbox/ofd-engine-build`.

The regular installer build runs this step before PyInstaller so end users do not need Java installed. OFD inputs are limited to 100 MiB compressed and 256 MiB expanded; exports are limited to 500 pages, 512 MiB, and 180 seconds.

See [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) and [LICENSE-OFDRW.txt](LICENSE-OFDRW.txt).
