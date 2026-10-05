"""Regression tests: recovery must not reset data or claim foreign ports."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
import container_bootstrap as b
import resilient_bootstrap as r

class RecoveryTests(unittest.TestCase):
 def test_dry_run_external_source_does_not_write_state(self):
  import contextlib,io
  args=b.build_parser().parse_args(['start','--dry-run','--no-open','--port','18088'])
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory)/'runtime';source=Path(directory)/'checkout';args.start_source_root=source
   with patch.object(b,'load_state',return_value={}),patch.object(b,'active_source_root',return_value=root),patch.object(b,'validate_update_source'),patch.object(b,'choose_web_port',return_value=18088),patch.object(b,'source_revision',return_value=None),patch.object(b,'source_image_tag',return_value='tag'),patch.object(b,'compose_command',return_value=['docker','compose','up']),patch.object(b,'copy_source_tree') as copy,patch.object(b,'write_state') as write,patch.object(b,'ensure_docker_ready') as docker,contextlib.redirect_stdout(io.StringIO()) as output:
    self.assertEqual(b.command_start(args,root),0)
    self.assertIn(str(source),output.getvalue())
    copy.assert_not_called();write.assert_not_called();docker.assert_not_called()
   with self.assertRaises(b.BootstrapError):b.relative_state_path(root,source)
 def test_network_classification(self):
  for text in ['tls: server did not echo the legacy session ID','i/o timeout','connection reset','503']:
   self.assertTrue(r.retryable(text))
  for text in ['EINTEGRITY ECONNRESET','no space left','manifest unknown','unauthorized tls:']:
   self.assertFalse(r.retryable(text))
 def test_retries_are_bounded(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);calls=[]
   def fail(command,**kw):
    calls.append(command);kw['log_path'].write_text('tls: handshake failure');return subprocess.CompletedProcess(command,1)
   with patch.object(b,'run_logged',side_effect=fail),patch.object(r.time,'sleep'):
    with self.assertRaises(b.BootstrapError):r.run_retry(b,['docker','pull','alpine:3.20'],root,{},root/'pull.log')
   self.assertEqual(len(calls),3)
 def test_cached_images_need_no_network(self):
  with patch.object(r,'inspect',return_value={'Id':'x'}),patch.object(r,'run_retry') as run:
   r.prepare(b,Path('.'),{'P2PKANBAN_IMAGE_TAG':'test'},Path('log'),build=False,offline=True)
   run.assert_not_called()
 def test_offline_missing_image_does_not_pull(self):
  with patch.object(r,'inspect',return_value=None),patch.object(r,'run_retry') as run:
   with self.assertRaises(b.BootstrapError):r.prepare(b,Path('.'),{'P2PKANBAN_IMAGE_TAG':'test'},Path('log'),build=False,offline=True)
   run.assert_not_called()
 def test_port_requires_identity_and_mounts(self):
  def volume(name,destination):return {'Type':'volume','Name':b.COMPOSE_PROJECT+'_'+name,'Destination':destination}
  secret=volume('bootstrap_secrets','/run/p2pkanban-secrets')
  gateway={'Config':{'Image':'p2pkanban/gateway:local','Labels':{'com.docker.compose.project':b.COMPOSE_PROJECT,'com.docker.compose.service':'gateway'}}}
  pg={'Config':{'Image':'postgres:16-alpine'},'Mounts':[secret,volume('postgres_data','/var/lib/postgresql/data')]}
  backend={'Config':{'Image':'p2pkanban/backend:2.0.0-old'},'Mounts':[secret]}
  with patch.object(b,'compose_service_container',side_effect=lambda root,service,**kw: pg if service=='postgres' else backend):
   self.assertTrue(r.verified_owner(b,Path('.'),gateway))
   pg['Mounts'][1]['Destination']='/wrong';self.assertFalse(r.verified_owner(b,Path('.'),gateway))
   gateway['Config']['Image']='another/app:local';self.assertFalse(r.verified_owner(b,Path('.'),gateway))
 def test_offline_receipt_rejects_wrong_source_and_image_ids(self):
  m={'format':'p2pkanban-runtime/1','sourceFingerprint':'abc','imageTag':'tag','images':{i:'id' for i in r.images('tag')}}
  with patch.object(b,'read_json_object',return_value=m),patch.object(b,'source_fingerprint',return_value='different'):
   with self.assertRaises(b.BootstrapError):r.offline_environment(b,Path('.'),{})
  with patch.object(b,'read_json_object',return_value=m),patch.object(b,'source_fingerprint',return_value='abc'),patch.object(r,'inspect',return_value={'Id':'replaced'}):
   with self.assertRaises(b.BootstrapError):r.offline_environment(b,Path('.'),{})
 def test_offline_uses_import_location_not_old_active_release(self):
  args=b.build_parser().parse_args(['start','--offline','--no-open'])
  root=Path('/fixture');env={}
  with patch.object(b,'load_state',return_value={'activeSourceRoot':'old'}),patch.object(b,'active_source_root') as active,patch.object(b,'choose_web_port',return_value=8080),patch.object(b,'source_revision',return_value=None),patch.object(r,'offline_environment',side_effect=b.BootstrapError('stop before Docker')) as offline:
   with self.assertRaises(b.BootstrapError):b.command_start(args,root)
   self.assertEqual(offline.call_args.args[1],root);active.assert_not_called()
 def test_backup_starts_existing_database_only(self):
  with patch.object(b,'compose_service_container',return_value={'Id':'existing-db','State':{'Running':False}}),patch.object(b,'docker_executable',return_value='docker'),patch.object(b,'run_capture',return_value=subprocess.CompletedProcess([],0)) as run:
   r.ready_existing_database(b,Path('.'),{})
   commands=[call.args[0] for call in run.call_args_list]
   self.assertEqual(commands[0],['docker','start','existing-db'])
   self.assertEqual(commands[1][:3],['docker','exec','existing-db'])
 def test_prepare_failure_does_not_change_stack_state(self):
  args=b.build_parser().parse_args(['start','--no-open'])
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory)
   with patch.object(b,'load_state',return_value={'status':'running'}),patch.object(b,'active_source_root',return_value=root),patch.object(b,'choose_web_port',return_value=8080),patch.object(b,'source_revision',return_value=None),patch.object(b,'source_image_tag',return_value='tag'),patch.object(b,'ensure_docker_ready'),patch.object(b,'validate_compose'),patch.object(b,'discover_owned_web_port',return_value=8080),patch.object(b,'compose_command',return_value=['docker','compose']),patch.object(r,'prepare',side_effect=b.BootstrapError('network')),patch.object(b,'write_state') as write,patch.object(b,'run_logged') as run:
    with self.assertRaises(b.BootstrapError):b.command_start(args,root)
    write.assert_not_called();run.assert_not_called()
 def test_takeover_orders_build_backup_then_up_without_pull(self):
  args=b.build_parser().parse_args(['start','--no-open']);order=[]
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory)
   def command(root,*args,**kw):return ['docker','compose',*args]
   with patch.object(b,'load_state',return_value={}),patch.object(b,'active_source_root',return_value=root),patch.object(b,'choose_web_port',return_value=8080),patch.object(b,'source_revision',return_value=None),patch.object(b,'source_image_tag',return_value='tag'),patch.object(b,'ensure_docker_ready'),patch.object(b,'validate_compose'),patch.object(b,'discover_owned_web_port',return_value=8080),patch.object(b,'compose_command',side_effect=command),patch.object(r,'prepare',side_effect=lambda *a,**k:order.append('prepare')),patch.object(r,'ready_existing_database'),patch.object(b,'create_database_backup',side_effect=lambda *a: (order.append('backup') or root,{})),patch.object(b,'write_state'),patch.object(b,'ensure_update_control_plane'),patch.object(b,'wait_until_ready',return_value=True),patch.object(b,'read_version',return_value='2.0.0'),patch.object(b,'run_logged',side_effect=lambda cmd,**k: (order.append(cmd) or subprocess.CompletedProcess(cmd,0))):
    b.command_start(args,root)
   self.assertEqual(order[:2],['prepare','backup']);self.assertEqual(order[2][-3:],['--no-build','--pull','never'])

if __name__=='__main__':unittest.main()
