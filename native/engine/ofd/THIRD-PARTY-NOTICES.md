# OFD converter notices

FLUKE invokes the separately developed OFDRW converter through a local Java process. The Python application does not contain OFDRW implementation code. The Java bridge is FLUKE code; two compatibility source files under `src/main/java/org/ofdrw` are modified copies from OFDRW 2.4.0 and are distributed under Apache License 2.0 with their upstream notices preserved.

## Included components

The following components are included as separate JARs in `engine/ofd/build/lib`:

| Component | Version | License | License material |
| --- | --- | --- | --- |
| OFDRW modules (`org.ofdrw:*`) | 2.4.0 | Apache-2.0 | `LICENSE-OFDRW.txt` |
| Apache Batik | 1.19 | Apache-2.0; bundled Tango and Pasodoble icons use CC BY-SA 2.5 | JAR `META-INF/LICENSE`, `META-INF/NOTICE` and `org/apache/batik/apps/svgbrowser/resources/LICENSE.icons.txt` |
| Apache Commons Codec, Compress, IO, Lang and Logging | 1.19.0, 1.28.0, 2.16.1, 3.18.0, 1.2 | Apache-2.0 | Each JAR contains `META-INF/LICENSE.txt` and `META-INF/NOTICE.txt` |
| Apache PDFBox and FontBox | 2.0.27 | Apache-2.0 | JAR `META-INF/LICENSE` and `META-INF/NOTICE` |
| Apache XML Graphics Commons | 2.11 | Apache-2.0 | JAR `META-INF/LICENSE` and `META-INF/NOTICE` |
| XML APIs and XML APIs Extensions | 1.4.01, 1.3.04 | Apache-2.0 plus the W3C and SAX/SAC notices documented in the artifacts | `license/` files inside each JAR |
| Zip4j | 2.11.3 | Apache-2.0 | `licenses/Apache-2.0.txt` |
| Bouncy Castle (`bcpkix`, `bcprov`, `bcutil`) | 1.84 | Bouncy Castle permissive license | `licenses/BouncyCastle-LICENSE.html` |
| TwelveMonkeys ImageIO modules | 3.13.0 | BSD-3-Clause | `licenses/TwelveMonkeys-BSD-3-Clause.txt` |
| dom4j | 2.1.4 | BSD-style, including the DOM4J naming and attribution conditions | `licenses/dom4j-LICENSE.txt` |
| Jaxen | 1.2.0 | BSD-style | JAR `META-INF/LICENSE.txt` |
| jbig2-imageio | 3.0.3 | Apache-2.0 | JAR `META-INF/LICENSE` and `META-INF/NOTICE` |
| UJMP core | 0.3.0 | LGPL-3.0-or-later | JAR `META-INF/LICENSE.TXT` and `META-INF/NOTICE.TXT`; matching source JAR in `licenses/` |
| SLF4J API and no-operation backend | 2.0.17 | MIT | JAR `META-INF/LICENSE.txt` |

`org.json:json:20141113` is deliberately excluded. It is not needed by the OFD text or page-rendering paths exercised by this bridge, and its Maven metadata identifies the nonstandard “JSON License.” The iText 7 artifacts requested by OFDRW's optional exporter are also excluded. PDF conversion uses rendered page images and Qt's PDF writer; it is not searchable text. PDFBox remains because OFDRW's AWT renderer uses its image blend-mode classes.

The LGPL UJMP dependency remains a distinct, replaceable JAR in the runtime classpath. The package also includes the corresponding source JAR so recipients can inspect, modify, rebuild, and substitute that library. The application does not merge UJMP into another archive.

A minimal Eclipse Temurin 21 runtime is generated from the official Windows x64 JDK archive during packaging. Temurin uses GPL-2.0 with the Classpath Exception; its license material is retained under `engine/ofd/build/java-runtime/legal`.

Relevant upstream references:

- [OFDRW 2.4.0 exporter documentation](https://github.com/ofdrw/ofdrw/blob/2.4.0/ofdrw-converter/doc/EXPORTER.md)
- [OFDRW 2.4.0 dependency manifest](https://github.com/ofdrw/ofdrw/blob/2.4.0/ofdrw-converter/pom.xml)
- [Bouncy Castle 1.84 license](https://github.com/bcgit/bc-java/blob/r1rv84/LICENSE.html)
- [TwelveMonkeys 3.13.0 license](https://github.com/haraldk/TwelveMonkeys/blob/twelvemonkeys-3.13.0/README.md#license)
- [dom4j 2.1.4 license](https://github.com/dom4j/dom4j/blob/version-2.1.4/LICENSE)
- [UJMP 0.3.0 metadata](https://central.sonatype.com/artifact/org.ujmp/ujmp-core/0.3.0)
- [Zip4j 2.11.3 license](https://github.com/srikanth-lingala/zip4j/blob/v2.11.3/LICENSE)
