from concurrent.futures import Future
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

from tools.probe_legacy_media import ENGINE_SHA256, HttpPreflight, resume_results, validate_results


class NativeResultTest(unittest.TestCase):
    def test_same_id_cannot_reuse_native_result_from_different_output_bytes(self):
        row = dict(id='a', name='tex', kind='Texture2D', width=4, height=4, output_sha256='new')
        result = dict(row, loaded=True, output_sha256='old')
        with self.assertRaisesRegex(RuntimeError, 'digest'):
            validate_results([row], [dict(result=result)])
        result['output_sha256'] = 'new'
        self.assertEqual(len(validate_results([row], [dict(result=result)])), 1)
        row['url'] = 'http://owned-server/asset.unity3d'
        with self.assertRaisesRegex(RuntimeError, 'HTTP preflight'):
            validate_results([row], [dict(result=result)])
        result['http_preflight_sha256'] = 'new'
        result['source_url'] = row['url']
        validate_results([row], [dict(result=result)])
        result['source_url'] = 'http://other-server/asset.unity3d'
        with self.assertRaisesRegex(RuntimeError, 'URL mismatch'):
            validate_results([row], [dict(result=result)])
    def test_equal_names_in_different_versions_match_by_id_not_completion_order(self):
        rows = [dict(id='a', name='same', kind='Texture2D', width=32, height=64),
                dict(id='b', name='same', kind='Texture2D', width=64, height=32)]
        events = [dict(result=dict(rows[1], loaded=True)), dict(result=dict(rows[0], loaded=True))]
        self.assertEqual(len(validate_results(rows, events)), 2)
        events[1]['result']['id'] = 'b'
        with self.assertRaisesRegex(RuntimeError, 'duplicate'):
            validate_results(rows, events)

    def test_decoder_granule_and_channels_must_match(self):
        row = dict(id='a', name='clip', kind='AudioClip', sample_rate=48000, channels=1,
                   source_samples=35712, ogg_granule_samples=35712)
        result = dict(id='a', name='clip', kind='AudioClip', frequency=48000, channels=1,
                      samples=35712, loaded=True)
        validate_results([row], [dict(result=result)])
        result['samples'] += 960
        with self.assertRaisesRegex(RuntimeError, 'metadata'):
            validate_results([row], [dict(result=result)])
        with self.assertRaisesRegex(RuntimeError, 'verification failed'):
            validate_results([row], [dict(error='native named asset missing')])


class PreflightWindowTest(unittest.TestCase):
    @patch('tools.probe_legacy_media.ThreadPoolExecutor')
    def test_stalled_native_consumer_cannot_download_rest_of_manifest(self, executor):
        futures = [Future() for _ in range(100)]
        executor.return_value.submit.side_effect = futures
        checks = HttpPreflight([{}] * 100, 2, attempts=5, timeout=60)
        self.addCleanup(checks.close)
        self.assertIsNone(checks.ready())
        self.assertEqual(executor.return_value.submit.call_count, 2)
        futures[0].set_result(1)
        for _ in range(20):
            self.assertEqual(checks.ready(), 0)
        self.assertEqual(executor.return_value.submit.call_count, 2)
        self.assertEqual(checks.take(0), 1)
        self.assertIsNone(checks.ready())
        self.assertEqual(executor.return_value.submit.call_count, 3)
        futures[1].set_exception(ValueError('HTTP digest mismatch'))
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            checks.take(1)

    @patch('tools.probe_legacy_media.ThreadPoolExecutor')
    def test_one_stalled_url_does_not_block_completed_urls_or_grow_window(self, executor):
        futures = [Future() for _ in range(5)]
        executor.return_value.submit.side_effect = futures
        checks = HttpPreflight([{}] * 5, 2, attempts=5, timeout=10)
        self.addCleanup(checks.close)
        self.assertIsNone(checks.ready())
        futures[1].set_result(0)
        self.assertEqual(checks.ready(), 1)
        self.assertEqual(checks.take(1), 0)
        self.assertIsNone(checks.ready())
        self.assertEqual(executor.return_value.submit.call_count, 3)
        futures[2].set_result(0)
        self.assertEqual(checks.ready(), 2)
        checks.take(2)
        self.assertFalse(futures[0].done())
        self.assertIsNone(checks.ready())
        self.assertEqual(len(checks.pending), 2)

    @unittest.skipUnless(shutil.which('node'), 'Node required for native retry policy tests')
    def test_native_transport_retries_release_requests_and_remain_bounded(self):
        source = Path('tools/probe_legacy_media.js').read_text(encoding='utf-8')
        # Execute the production functions with a disposed WWW/GC-handle spy;
        # no Unity installation is required to exercise the retry state machine.
        functions = source[source.index('function retryDownload'):source.index('function step')]
        test = r'''
const assert=require('node:assert/strict');
let current,settings={attempts:3},events=[],released=[],disposed=[];
const wwwDispose='Dispose',call=(m,r)=>disposed.push(r),free=h=>released.push(h),send=e=>events.push(e);
FUNCTIONS
assert.equal(transientWWW('Failed downloading http://owned/404.unity3d'),true);
assert.equal(transientWWW('404 Not Found: http://owned/asset'),false);
assert.equal(transientWWW('503 Service Unavailable'),true);
assert.equal(transientWWW('another asset bundle with the same files are already loaded'),false);
assert.equal(transientWWW('native named asset missing'),false);
current={url:'http://owned/asset',id:'a',name:'clip',request:1,handles:[11,12],started:Date.now()};
assert.equal(retryDownload('connection closed'),true);
assert.deepEqual(released,[11,12]);assert.deepEqual(disposed,[1]);
assert.equal(current.request,null);assert.equal(events.length,1);
current.request=2;current.handles=[13];
assert.equal(retryDownload('timeout'),true);
assert.equal(retryDownload('timeout'),false);assert.equal(events.length,2);
current.httpRetries=0;current.bundle={};assert.equal(retryDownload('decode error'),false);
'''.replace('FUNCTIONS', functions)
        subprocess.run(['node', '-e', test], check=True, capture_output=True, text=True)


class ResumeTest(unittest.TestCase):
    def setUp(self):
        self.row = dict(id='a', name='tex', kind='Texture2D', width=4, height=8,
                        output_sha256='bytes', url='http://owned/a')
        result = dict(self.row, loaded=True, source_url=self.row['url'], http_preflight_sha256='bytes')
        self.previous = dict(engine_sha256=ENGINE_SHA256, manifest_sha256='manifest',
                             probe_sha256='probe', events=[dict(result=result),
                             dict(retry=True, id='b'), dict(error='HTTP timeout', phase='driver')])

    def test_resume_keeps_valid_successes_and_retry_evidence_but_not_failed_results(self):
        events, accepted = resume_results([self.row], self.previous, 'manifest', 'probe', set())
        self.assertEqual(accepted, {'a'})
        self.assertTrue(events[0]['retry'])
        validate_results([self.row], events)
        self.assertTrue(any('error' in event for event in self.previous['events']))

    def test_changed_input_engine_probe_or_native_metadata_cannot_resume(self):
        for key in ('engine_sha256', 'manifest_sha256', 'probe_sha256'):
            changed = dict(self.previous, **{key:'changed'})
            with self.assertRaisesRegex(ValueError, 'fingerprint'):
                resume_results([self.row], changed, 'manifest', 'probe', set())
        self.previous['events'][0]['result']['width'] = 16
        with self.assertRaisesRegex(RuntimeError, 'dimensions'):
            resume_results([self.row], self.previous, 'manifest', 'probe', set())

    def test_duplicate_unknown_ids_and_missing_playback_cannot_be_reused(self):
        duplicate = dict(self.previous, events=self.previous['events']*2)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            resume_results([self.row], duplicate, 'manifest', 'probe', set())
        with self.assertRaisesRegex(ValueError, 'unknown'):
            resume_results([], self.previous, 'manifest', 'probe', set())
        events, accepted = resume_results([self.row], self.previous, 'manifest', 'probe', {'tex'})
        self.assertEqual(accepted, set())
        self.assertFalse(any('result' in event for event in events))
