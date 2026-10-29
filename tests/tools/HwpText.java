import java.io.File;
import java.io.PrintStream;

import kr.dogfoot.hwplib.object.HWPFile;
import kr.dogfoot.hwplib.reader.HWPReader;
import kr.dogfoot.hwplib.tool.textextractor.TextExtractMethod;
import kr.dogfoot.hwplib.tool.textextractor.TextExtractOption;
import kr.dogfoot.hwplib.tool.textextractor.TextExtractor;

/** Test helper: print the full text of each HWP given, separated by \u0000. */
public class HwpText {
    public static void main(String[] args) throws Exception {
        PrintStream out = new PrintStream(System.out, true, "UTF-8");
        for (String a : args) {
            try {
                HWPFile f = HWPReader.fromFile(new File(a));
                TextExtractOption opt = new TextExtractOption(TextExtractMethod.InsertControlTextBetweenParagraphText, false);
                opt.setInsertParaHead(false);  // auto-numbering is generated, not stored text
                out.print(TextExtractor.extract(f, opt));
            } catch (Throwable e) {
                out.print("<<ERROR " + e + ">>");
            }
            out.print('\u0000');
        }
    }
}
