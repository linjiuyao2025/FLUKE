package com.fluke.ofd;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

import org.ofdrw.converter.export.HTMLExporter;
import org.ofdrw.converter.export.ImageExporter;
import org.ofdrw.converter.export.OFDExporter;
import org.ofdrw.converter.export.TextExporter;

/** Command-line adapter used by FLUKE's local converter. */
public final class OfdBridge {
    private OfdBridge() {
    }

    public static void main(String[] args) {
        if (args.length != 3) {
            System.err.println("Expected: <input.ofd> <target> <output-path>");
            System.exit(2);
        }

        Path source = Paths.get(args[0]);
        String target = args[1];
        Path output = Paths.get(args[2]);
        try {
            if (!Files.isRegularFile(source)) {
                throw new IllegalArgumentException("Input file is missing.");
            }
            Path parent = target.equals("png") ? output : output.toAbsolutePath().getParent();
            if (parent != null) {
                Files.createDirectories(parent);
            }

            OFDExporter exporter;
            switch (target) {
                case "html":
                    exporter = new HTMLExporter(source, output);
                    break;
                case "text":
                    exporter = new TextExporter(source, output);
                    break;
                case "png":
                    Files.createDirectories(output);
                    exporter = new ImageExporter(source, output, "PNG", 300d / 25.4d);
                    break;
                default:
                    throw new IllegalArgumentException("Unsupported target: " + target);
            }
            try (OFDExporter closeable = exporter) {
                closeable.export();
            }
        } catch (Exception exception) {
            System.err.println(exception.getClass().getSimpleName() + ": " + exception.getMessage());
            System.exit(1);
        }
    }
}
