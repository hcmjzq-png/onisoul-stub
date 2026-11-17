import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.publish_navigator_compat import ORIGINALS, install, snapshot, validate_plan


class NavigatorPublishTest(unittest.TestCase):
    def fixture(self, root):
        release, assets, backups = root/'release', root/'assets', root/'backups'
        rows = []
        for family in range(1, 9):
            for color in range(1, 6):
                for role in ('bust', 'icon'):
                    nid = f'navi8000{family}01'
                    name = f'cch1_8000{family}_0{color}_3_01' if role == 'bust' else f'item12_8000{family}0{color}'
                    original = (nid, color, role) in ORIGINALS
                    category = 'cch' if role == 'bust' else 'item'
                    relative = category+'/'+hashlib.md5(name.encode('utf-16le')).hexdigest()+'.unity3d'
                    data = name.encode()
                    path = (assets if original else release)/'bundles'/relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                    textures = [dict(name=name, width=1024, height=1024)] if role == 'bust' else [
                        dict(name=name+'_01', width=64, height=64), dict(name=name+'_02', width=128, height=128)]
                    rows.append(dict(navigator=nid, color=color, role=role, relative=relative,
                        url='/client/pc/jp/assets/'+relative, preserved_original=original,
                        textures=textures, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                        provenance='original_pc_preserved' if original else 'ai_reference_compatibility'))
        (assets/'unrelated-voice').write_bytes(b'keep voice')
        plan=dict(schema=1,kind='navigator_compatibility_candidate',files=rows)
        (release/'manifest.json').write_text(json.dumps(plan))
        return release, assets, backups, rows, plan

    def test_additive_idempotent_and_existing_originals_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            release, assets, backups, rows, _ = self.fixture(Path(temp))
            before=snapshot(assets)
            result=install(release,assets,backups,verify_http=lambda rows:len(rows))
            self.assertEqual((result['installed'],result['http_verified']), (71,80))
            self.assertTrue(all(snapshot(assets)[k]==v for k,v in before.items()))
            self.assertEqual(install(release,assets,backups)['installed'],0)

    def test_conflicting_original_or_target_aborts_before_any_publish(self):
        for original in (True,False):
            with self.subTest(original=original),tempfile.TemporaryDirectory() as temp:
                release,assets,backups,rows,_=self.fixture(Path(temp))
                row=next(r for r in rows if r['preserved_original']==original)
                path=assets/'bundles'/row['relative'];path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(b'different existing content')
                before=snapshot(assets)
                with self.assertRaisesRegex(ValueError,'refusing replacement'):
                    install(release,assets,backups)
                self.assertEqual(snapshot(assets),before)
                self.assertFalse(backups.exists())

    def test_http_failure_rolls_back_new_files_only(self):
        with tempfile.TemporaryDirectory() as temp:
            release,assets,backups,rows,_=self.fixture(Path(temp));before=snapshot(assets)
            def failure(rows):raise RuntimeError('HTTP digest mismatch')
            with self.assertRaisesRegex(RuntimeError,'HTTP digest mismatch'):
                install(release,assets,backups,verify_http=failure)
            self.assertEqual(snapshot(assets),before)

    def test_concurrent_creation_is_never_overwritten_or_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            release,assets,backups,rows,_=self.fixture(Path(temp));link=os.link;created=[]
            def race(source,target):
                if len(created)==2:target.write_bytes(b'concurrent external bytes')
                created.append(target);return link(source,target)
            with patch('tools.publish_navigator_compat.os.link',side_effect=race):
                with self.assertRaisesRegex(ValueError,'concurrent navigator change'):
                    install(release,assets,backups)
            self.assertEqual(created[2].read_bytes(),b'concurrent external bytes')
            self.assertFalse(created[0].exists());self.assertFalse(created[1].exists())

    def test_corrupt_upload_and_voice_or_path_injection_refused(self):
        for mode in ('corrupt','path','voice'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as temp:
                release,assets,backups,rows,plan=self.fixture(Path(temp))
                row=next(r for r in rows if not r['preserved_original'])
                if mode=='corrupt':(release/'bundles'/row['relative']).write_bytes(b'truncated')
                elif mode=='path':row['relative']='../escape'
                else:row['relative']='vse/'+Path(row['relative']).name
                (release/'manifest.json').write_text(json.dumps(plan));before=snapshot(assets)
                with self.assertRaises(ValueError):install(release,assets,backups)
                self.assertEqual(snapshot(assets),before)


if __name__=='__main__':unittest.main()
