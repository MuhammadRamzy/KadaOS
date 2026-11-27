"""Offline checks for file-action kinds, naming, and applicability (no conversions run)."""
import importlib.util, tempfile, unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('fa', Path(__file__).resolve().parents[1] / 'config/desktop/fileactions.py')
fa = importlib.util.module_from_spec(spec); spec.loader.exec_module(fa)


class FileActions(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(fa.kind_of('/x/a.PNG'), 'image')
        self.assertEqual(fa.kind_of('/x/a.mkv'), 'video')
        self.assertEqual(fa.kind_of('/x/a.docx'), 'document')
        self.assertEqual(fa.kind_of('/x/a.pdf'), 'pdf')
        self.assertEqual(fa.kind_of('/x/a.unknownext'), 'other')

    def test_output_path_never_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'photo.png'; src.write_text('x')
            # new extension
            self.assertEqual(fa.output_path(src, 'webp').name, 'photo.webp')
            # collision -> numbered
            (Path(d) / 'photo.webp').write_text('y')
            self.assertEqual(fa.output_path(src, 'webp').name, 'photo (2).webp')
            # same-ext conversion must not target the source itself
            self.assertNotEqual(fa.output_path(src, 'png'), src)

    def test_actions_scope_to_selection(self):
        img = [p for p in ['/x/a.png', '/x/b.jpg']]
        ids = [a for a, _ in fa.actions_for(img)]
        self.assertIn('img_convert', ids); self.assertIn('img_pdf', ids)
        self.assertNotIn('vid_convert', ids)
        # mixed kinds -> only cross-kind actions
        mixed = [a for a, _ in fa.actions_for(['/x/a.png', '/x/c.mp4'])]
        self.assertEqual(set(mixed), {'make_zip', 'copy_path'})
        # merge needs >=2 pdfs
        self.assertNotIn('pdf_merge', [a for a, _ in fa.actions_for(['/x/a.pdf'])])
        self.assertIn('pdf_merge', [a for a, _ in fa.actions_for(['/x/a.pdf', '/x/b.pdf'])])


if __name__ == '__main__': unittest.main()
