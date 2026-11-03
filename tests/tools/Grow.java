import java.io.File;
import kr.dogfoot.hwplib.object.HWPFile;
import kr.dogfoot.hwplib.object.bodytext.Section;
import kr.dogfoot.hwplib.object.bodytext.paragraph.Paragraph;
import kr.dogfoot.hwplib.reader.HWPReader;
import kr.dogfoot.hwplib.writer.HWPWriter;

/** Test helper: repeat every section's body `factor` times to make a big document. */
public class Grow {
    public static void main(String[] a) throws Exception {
        HWPFile f = HWPReader.fromFile(new File(a[0]));
        int factor = Integer.parseInt(a[2]);
        for (Section s : f.getBodyText().getSectionList()) {
            Paragraph[] orig = s.getParagraphs();
            // keep the first paragraph (it carries the section definition) only once
            for (int k = 1; k < factor; k++)
                for (int i = 1; i < orig.length; i++)
                    s.insertParagraph(s.getParagraphCount(), orig[i].clone());
        }
        HWPWriter.toFile(f, a[1]);
    }
}
