package kr.hwp2x.engine;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.util.Enumeration;
import java.util.zip.CRC32;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import java.util.zip.ZipOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;

import kr.dogfoot.hwp2hwpx.Hwp2Hwpx;
import kr.dogfoot.hwplib.object.HWPFile;
import kr.dogfoot.hwplib.reader.HWPReader;
import kr.dogfoot.hwpxlib.object.HWPXFile;
import kr.dogfoot.hwpxlib.writer.HWPXWriter;

/**
 * hwp2x conversion engine.
 *
 * Modes:
 *   Main <in.hwp> <out.hwpx>   convert one file
 *   Main --serve               read jobs from stdin, one per line: "<in>\t<out>"
 *                              and answer one line per job on stdout:
 *                              "OK\t<ms>"  or  "ERR\t<code>\t<message>"
 *   Main --version             print engine version
 *
 * Keeping one JVM alive for a batch avoids paying JVM start-up per file.
 * Output is written to a temporary file next to the target and moved into
 * place only on success, so a failed conversion never leaves a broken .hwpx.
 */
public final class Main {
    public static final String VERSION = "1";

    private static final byte[] OLE_SIGNATURE = {
            (byte) 0xD0, (byte) 0xCF, 0x11, (byte) 0xE0,
            (byte) 0xA1, (byte) 0xB1, 0x1A, (byte) 0xE1};
    private static final byte[] ZIP_SIGNATURE = {0x50, 0x4B, 0x03, 0x04};

    public static void main(String[] args) throws Exception {
        if (args.length == 1 && args[0].equals("--version")) {
            System.out.println("hwp2x-engine " + VERSION);
            return;
        }
        if (args.length == 1 && args[0].equals("--serve")) {
            serve();
            return;
        }
        if (args.length == 2) {
            String r = convertOne(args[0], args[1]);
            System.out.println(r);
            System.exit(r.startsWith("OK") ? 0 : 1);
        }
        System.err.println("usage: Main <in.hwp> <out.hwpx> | --serve | --version");
        System.exit(2);
    }

    private static void serve() throws Exception {
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        PrintWriter out = new PrintWriter(new OutputStreamWriter(System.out, StandardCharsets.UTF_8), false);
        out.println("READY\t" + VERSION);
        out.flush();
        String line;
        while ((line = in.readLine()) != null) {
            if (line.isEmpty()) continue;
            int tab = line.indexOf('\t');
            String result = tab < 0
                    ? err("BADJOB", "malformed job line")
                    : convertOne(line.substring(0, tab), line.substring(tab + 1));
            out.println(result);
            out.flush();
        }
    }

    static String convertOne(String inPath, String outPath) {
        long t0 = System.currentTimeMillis();
        File inFile = new File(inPath);
        if (!inFile.isFile()) return err("NOTFOUND", "file not found");

        try {
            byte[] head = readHead(inFile, 8);
            if (startsWith(head, ZIP_SIGNATURE)) return err("ALREADY_HWPX", "already HWPX (zip) format");
            if (!startsWith(head, OLE_SIGNATURE)) return err("NOT_HWP5", "not an HWP 5.x file (HWP 3.x or another format)");
        } catch (Exception e) {
            return err("READ", e.toString());
        }

        HWPFile hwp;
        try {
            hwp = HWPReader.fromFile(inFile);
        } catch (Throwable e) {
            return err("READ", describe(e));
        }
        if (hwp.getFileHeader().hasPassword()) return err("PASSWORD", "password-protected document");
        // A distribution document carries the author's copy/print restriction.
        // Converting it would silently drop that restriction, so refuse.
        if (hwp.getFileHeader().isDistribution()) return err("DISTRIBUTION", "distribution (copy/print-restricted) document");

        Path target = new File(outPath).getAbsoluteFile().toPath();
        Path tmp = null;
        try {
            HWPXFile hwpx = Hwp2Hwpx.toHWPX(hwp);
            Path dir = target.getParent();
            if (dir != null) Files.createDirectories(dir);
            tmp = Files.createTempFile(dir, ".hwp2x-", ".part");
            HWPXWriter.toFilepath(hwpx, tmp.toString());
            int removed = repackage(tmp);
            Files.move(tmp, target, StandardCopyOption.REPLACE_EXISTING);
            tmp = null;
            return "OK\t" + (System.currentTimeMillis() - t0)
                    + (removed > 0 ? "\tWARN:removed " + removed + " invalid XML control characters" : "");
        } catch (Throwable e) {
            return err("CONVERT", describe(e));
        } finally {
            if (tmp != null) {
                try { Files.deleteIfExists(tmp); } catch (Exception ignored) { }
            }
        }
    }

    /**
     * Rewrite the archive hwpxlib produced so that it is a valid package:
     *  - OCF packaging (which HWPX follows) requires "mimetype" to be the first
     *    entry and stored uncompressed; hwpxlib deflates it.
     *  - Source documents sometimes carry control characters (e.g. inside a
     *    corrupt font name) that hwpxlib writes verbatim, which XML 1.0 forbids
     *    and which make the part unparseable. They are dropped from XML parts.
     * Returns the number of characters removed.
     */
    static int repackage(Path zipPath) throws Exception {
        int removed = 0;
        Path fixed = Files.createTempFile(zipPath.getParent(), ".hwp2x-", ".fix");
        try {
            try (ZipFile src = new ZipFile(zipPath.toFile());
                 ZipOutputStream dst = new ZipOutputStream(Files.newOutputStream(fixed))) {
                ZipEntry mt = src.getEntry("mimetype");
                if (mt != null) {
                    byte[] data = readAll(src.getInputStream(mt));
                    ZipEntry e = new ZipEntry("mimetype");
                    e.setMethod(ZipEntry.STORED);
                    e.setSize(data.length);
                    e.setCompressedSize(data.length);
                    CRC32 crc = new CRC32();
                    crc.update(data);
                    e.setCrc(crc.getValue());
                    dst.putNextEntry(e);
                    dst.write(data);
                    dst.closeEntry();
                }
                Enumeration<? extends ZipEntry> en = src.entries();
                byte[] buf = new byte[64 * 1024];
                while (en.hasMoreElements()) {
                    ZipEntry e = en.nextElement();
                    String name = e.getName();
                    if (name.equals("mimetype")) continue;
                    dst.putNextEntry(new ZipEntry(name));
                    if (name.endsWith(".xml") || name.endsWith(".hpf")) {
                        byte[] data = readAll(src.getInputStream(e));
                        int n = stripXmlControlChars(data);
                        removed += data.length - n;
                        dst.write(data, 0, n);
                    } else {
                        try (InputStream in = src.getInputStream(e)) {
                            int r;
                            while ((r = in.read(buf)) > 0) dst.write(buf, 0, r);
                        }
                    }
                    dst.closeEntry();
                }
            }
            Files.move(fixed, zipPath, StandardCopyOption.REPLACE_EXISTING);
            fixed = null;
        } finally {
            if (fixed != null) Files.deleteIfExists(fixed);
        }
        return removed;
    }

    /**
     * Remove C0 control characters other than TAB, LF and CR, in place.
     * Safe on UTF-8 bytes: these values never occur inside multi-byte sequences.
     * Returns the new length.
     */
    static int stripXmlControlChars(byte[] data) {
        int w = 0;
        for (int r = 0; r < data.length; r++) {
            byte b = data[r];
            if (b >= 0 && b < 0x20 && b != 0x09 && b != 0x0A && b != 0x0D) continue;
            data[w++] = b;
        }
        return w;
    }

    private static byte[] readAll(InputStream in) throws Exception {
        try (InputStream i = in) {
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int r;
            while ((r = i.read(buf)) > 0) bo.write(buf, 0, r);
            return bo.toByteArray();
        }
    }

    private static byte[] readHead(File f, int n) throws Exception {
        byte[] b = new byte[n];
        try (FileInputStream in = new FileInputStream(f)) {
            int read = 0;
            while (read < n) {
                int r = in.read(b, read, n - read);
                if (r < 0) break;
                read += r;
            }
            if (read < n) return new byte[0];
        }
        return b;
    }

    private static boolean startsWith(byte[] data, byte[] sig) {
        if (data.length < sig.length) return false;
        for (int i = 0; i < sig.length; i++) if (data[i] != sig[i]) return false;
        return true;
    }

    private static String describe(Throwable e) {
        String msg = e.getMessage();
        StackTraceElement[] st = e.getStackTrace();
        String where = st.length > 0 ? " @ " + st[0].getClassName() + "." + st[0].getMethodName() : "";
        return e.getClass().getSimpleName() + (msg != null ? ": " + msg : "") + where;
    }

    private static String err(String code, String message) {
        return "ERR\t" + code + "\t" + message.replace('\t', ' ').replace('\n', ' ').replace('\r', ' ');
    }
}
