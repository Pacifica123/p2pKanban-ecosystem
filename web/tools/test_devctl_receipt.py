"""Проверки преобразования результатов devctl без запуска команд."""
import json, tempfile, unittest
from pathlib import Path
from devctl_receipt import build_receipt
class ReceiptTests(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name);self.logs=self.root/'.devctl/archive/run/logs';self.logs.mkdir(parents=True)
  self.project={'schemaVersion':1,'projectId':'01991234-1111-7111-8111-111111111111','resource':{'provider':'devctl'}}
  self.run={'patchId':'fixture','patchSha256':'a'*64,'commitSha':'b'*40,'status':'applied','finishedAt':'2026-09-06T00:00:00Z','archiveDir':'.devctl/archive/run'}
  self.manifest={'patchId':'fixture','checks':[{'name':'build'}]};self.write();(self.logs/'check-01-build.log').write_text('# Проверка: build\nКод возврата: 0\n',encoding='utf-8')
 def write(self):
  (self.root/'.devctl/state.json').write_text(json.dumps({'runs':[self.run]}));(self.logs/'manifest.json').write_text(json.dumps(self.manifest))
 def test_stable(self):
  a=build_receipt(self.root,self.project);self.assertEqual(a,build_receipt(self.root,self.project));self.assertEqual(a['checks'],[{'name':'build','status':'passed'}])
 def test_stdout_not_evidence(self):
  (self.logs/'check-01-build.log').write_text('# Проверка: build\nКод возврата: 1\n\n\n\n\nКод возврата: 0',encoding='utf-8')
  with self.assertRaises(ValueError):build_receipt(self.root,self.project)
 def test_missing_check(self):
  (self.logs/'check-01-build.log').unlink()
  with self.assertRaises(ValueError):build_receipt(self.root,self.project)
 def test_failed(self):
  self.run['status']='failed';self.write()
  with self.assertRaises(ValueError):build_receipt(self.root,self.project)
 def test_escape(self):
  self.run['archiveDir']='../outside';self.write()
  with self.assertRaises(ValueError):build_receipt(self.root,self.project)
 def test_wrong_project(self):
  self.manifest['integrations']={'p2pKanban':{'schemaVersion':1,'projectId':'another'}};self.write()
  with self.assertRaises(ValueError):build_receipt(self.root,self.project)
if __name__=='__main__':unittest.main()
