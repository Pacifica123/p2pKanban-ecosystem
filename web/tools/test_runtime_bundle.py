"""Exercise bundle file integrity/identity gates with an isolated Docker adapter."""
import argparse
import json
import tempfile
import unittest
import zipfile
from contextlib import ExitStack
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch
import container_bootstrap as b
import resilient_bootstrap as r

class Bundles(unittest.TestCase):
 def test_roundtrip_and_corruption_before_load(self):
  with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
   root=Path(directory);archive=root/'runtime.zip';calls=[];metadata={ref:{'Id':'sha256:'+str(i)*64,'Os':'linux','Architecture':'amd64'} for i,ref in enumerate(r.images('tag'))}
   def capture(command,**kwargs):
    calls.append(command)
    if 'save' in command:Path(command[command.index('-o')+1]).write_bytes(b'docker-save-fixture')
    return CompletedProcess(command,0,stdout='linux/amd64' if 'version' in command else '')
   for target,name,value in [(b,'ensure_docker_ready',None),(r,'prepare',None),(b,'source_image_tag','tag'),(b,'source_revision',None),(b,'source_fingerprint','fingerprint'),(b,'read_version','2.0.0'),(b,'docker_executable','docker')]:stack.enter_context(patch.object(target,name,return_value=value))
   stack.enter_context(patch.object(b,'run_capture',side_effect=capture));stack.enter_context(patch.object(r,'inspect',side_effect=lambda _b,_root,ref:metadata.get(ref)))
   r.bundle_export(argparse.Namespace(output=str(archive)),root,b)
   r.bundle_import(argparse.Namespace(bundle=str(archive)),root,b)
   env={};r.offline_environment(b,root,env);self.assertEqual(env['P2PKANBAN_IMAGE_TAG'],'tag')
   self.assertTrue(any('load' in c for c in calls));self.assertFalse(any('volume' in c for c in calls))
   with zipfile.ZipFile(archive) as z:manifest=z.read('manifest.json')
   damaged=root/'damaged.zip'
   with zipfile.ZipFile(damaged,'w') as z:z.writestr('manifest.json',manifest);z.writestr('images.tar',b'changed')
   calls.clear()
   with self.assertRaisesRegex(b.BootstrapError,'checksum'):r.bundle_import(argparse.Namespace(bundle=str(damaged)),root,b)
   self.assertFalse(any('load' in c for c in calls))
   wrong=root/'wrong.zip';m=json.loads(manifest);m['platform']=['linux','arm64']
   with zipfile.ZipFile(wrong,'w') as z:z.writestr('manifest.json',json.dumps(m));z.writestr('images.tar',b'docker-save-fixture')
   with self.assertRaisesRegex(b.BootstrapError,'Архитектура'):r.bundle_import(argparse.Namespace(bundle=str(wrong)),root,b)
   self.assertFalse(any('load' in c for c in calls))
 def test_zip_paths_never_extracted(self):
  with tempfile.TemporaryDirectory() as directory,patch.object(b,'ensure_docker_ready'):
   root=Path(directory);archive=root/'bad.zip'
   with zipfile.ZipFile(archive,'w') as z:z.writestr('../outside','payload')
   with self.assertRaisesRegex(b.BootstrapError,'состав'):r.bundle_import(argparse.Namespace(bundle=str(archive)),root,b)
   self.assertFalse((root.parent/'outside').exists())

if __name__=='__main__':unittest.main()
