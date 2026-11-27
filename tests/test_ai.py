"""Offline regressions for AI boundaries and failure behavior; never run model commands."""
import contextlib
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('fai', Path(__file__).resolve().parents[1] / 'config/ai/fai.py')
fai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fai)


class Diagnostics(unittest.TestCase):
    def test_mutation_and_secret_requests_never_execute(self):
        commands = ['nvidia-smi -pl 100', 'nvidia-smi -f /tmp/output', 'git branch -D main',
                    'git -c core.pager=anything log', 'ip link set eth0 down',
                    'nmcli connection delete example', 'journalctl --vacuum-time=1s',
                    'systemctl --user restart ollama-local', 'systemctl status -H remote',
                    'docker compose down', 'docker inspect example', 'env', 'printenv',
                    'ps eww', 'cat /proc/self/environ', 'cat ~/.codex/auth.json',
                    'cat ~/.config/private/.env.production', 'date -s tomorrow',
                    'ss -K', 'dpkg -s --configure', 'free -h; touch /tmp/should-not-exist']
        with patch.object(fai.subprocess, 'run') as run:
            for command in commands:
                with self.subTest(command=command):
                    self.assertTrue(fai.run_readonly(command).startswith('REFUSED:'))
            run.assert_not_called()

    def test_supported_diagnostics(self):
        for command in ['df -h', 'free -h', 'systemctl --failed', 'systemctl --user status ollama-local',
                        'journalctl -b -p err', 'nmcli device', 'nmcli -t -f DEVICE,STATE device',
                        'hyprctl monitors -j', 'ps -eo pid,comm,%cpu,%mem --sort=-%mem',
                        'nvidia-smi', 'cat /etc/os-release', 'head -n 20 /proc/meminfo', 'git status --short']:
            with self.subTest(command=command): self.assertTrue(fai.diagnostic_argv(command))

    def test_symlink_cannot_escape_diagnostic_docs(self):
        with tempfile.TemporaryDirectory() as d, patch.object(fai, 'HOME', Path(d)):
            docs = Path(d) / 'KadaOS/docs'; docs.mkdir(parents=True)
            outside = Path(d) / 'private.txt'; outside.write_text('fixture')
            (docs / 'linked.txt').symlink_to(outside)
            with self.assertRaises(ValueError): fai.diagnostic_argv(f'cat {docs}/linked.txt')


    def test_status_survives_gpu_and_systemctl_failures(self):
        def fake(outcome):
            def run(cmd, **kw):
                if cmd[0] == 'nvidia-smi':
                    if outcome == 'missing': raise FileNotFoundError
                    if outcome == 'mismatch':
                        return SimpleNamespace(returncode=18, stdout='Failed to initialize NVML: Driver/library version mismatch\nNVML library version: 595.99\n', stderr='')
                    if outcome == 'malformed': return SimpleNamespace(returncode=0, stdout='garbage', stderr='')
                    return SimpleNamespace(returncode=0, stdout='45, 3 %, 100 MiB, 8151 MiB, 5.00 W\n', stderr='')
                if cmd[:2] == ['systemctl', '--failed'] or cmd[:3] == ('systemctl', '--failed', '--no-legend'):
                    return SimpleNamespace(returncode=1, stdout='', stderr='Access denied')
                return SimpleNamespace(returncode=0, stdout='', stderr='')
            return run
        for outcome, expect in [('mismatch', 'reboot to fix'), ('missing', 'not installed'),
                                ('malformed', 'unknown'), ('ok', 'utilization 3 %')]:
            with self.subTest(outcome=outcome), patch.object(fai.subprocess, 'run', side_effect=fake(outcome)):
                out = fai.system_status()
                gpu = next(l for l in out.splitlines() if l.startswith('NVIDIA GPU'))
                self.assertIn(expect, gpu)
                self.assertIn('could not check system services', out)


    def test_setup_doc_search_skips_history_and_admits_no_match(self):
        d = str(fai.SETUP_DOCS)
        hits = [(0.9, d + '/reviews/2026-09-26-final-audit.md', 'old'), (0.8, d + '/HANDOFF.md', 'old'),
                (0.7, d + '/plans/desktop-design-brief.md', 'proposal'), (0.6, d + '/HYPRLAND_GUIDE.md', 'current')]
        with patch.object(fai, 'search', return_value=hits):
            out = fai.search_setup_docs('shortcut')
        self.assertIn('HYPRLAND_GUIDE.md', out)
        for old in ('reviews/', 'HANDOFF', 'plans/'): self.assertNotIn(old, out)
        with patch.object(fai, 'search', return_value=hits[:3]):
            self.assertIn('do not guess', fai.search_setup_docs('x'))

    def test_system_agent_surfaces_model_errors(self):
        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): pass
        with patch.object(fai, 'ensure_server'), patch.object(fai, 'sysinfo', return_value=''), \
             patch.object(fai, '_req', return_value=Resp(b'{"error": "model not found"}\n')):
            with self.assertRaisesRegex(RuntimeError, 'model not found'):
                fai.system_agent('hi', show=lambda *a, **k: None)


class Answers(unittest.TestCase):
    def test_think_tags_at_every_chunk_boundary(self):
        text = 'Before<think>hidden reasoning</think>After'
        for i in range(len(text)+1):
            self.assertEqual(''.join(fai.visible_tokens([text[:i], text[i:]])), 'BeforeAfter')
        self.assertEqual(''.join(fai.visible_tokens(list(text))), 'BeforeAfter')
        self.assertEqual(''.join(fai.visible_tokens(['<think>unfinished'])), '')
        self.assertEqual(''.join(fai.visible_tokens(['normal < text'])), 'normal < text')

    def test_failed_window_preserves_clipboard_and_does_not_paste(self):
        args = SimpleNamespace(text_file=None, question='hello', action='free', claude=False, paste_to='0x123')
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(fai, 'read_text', return_value=''))
            stack.enter_context(patch.object(fai, 'header'))
            stack.enter_context(patch.object(fai, 'redraw'))
            stack.enter_context(patch.object(fai.os, 'system'))
            stack.enter_context(patch.object(fai, 'getkey', return_value='\r'))
            stack.enter_context(patch.object(fai, 'chat_stream', side_effect=RuntimeError('offline')))
            copy = stack.enter_context(patch.object(fai, 'copy'))
            paste = stack.enter_context(patch.object(fai.subprocess, 'Popen'))
            out = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            fai.cmd_window(args)
            copy.assert_not_called(); paste.assert_not_called()
            self.assertIn('offline', out.getvalue())
            self.assertNotIn('✔ Copied', out.getvalue())

    def test_cmd_reply_in_code_fence_yields_the_command(self):
        for reply, want in [('```bash\ndf -h\n```', 'df -h'), ('`df -h`', 'df -h'), ('df -h\nextra', 'df -h'),
                            ('```\n```', ''), ('', '')]:
            with self.subTest(reply=reply): self.assertEqual(fai.first_command(reply), want)

    def test_handoff_only_offers_explicit_text(self):
        answer = 'Try this:\n```bash\njournalctl -b -p err\n```\nThen read /tmp/diagnosis.txt.'
        self.assertEqual(fai.handoff_candidates(answer), ['journalctl -b -p err', '/tmp/diagnosis.txt'])
        self.assertEqual(fai.handoff_candidates('Use `systemctl --user status ollama-local`.'),
                         ['systemctl --user status ollama-local'])

    def test_opening_handoff_does_not_regenerate_answer(self):
        args = SimpleNamespace(text_file=None, question='help', action='free', claude=False, paste_to=None)
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(fai, 'read_text', return_value=''))
            stack.enter_context(patch.object(fai, 'header'))
            stack.enter_context(patch.object(fai, 'redraw'))
            stack.enter_context(patch.object(fai.os, 'system'))
            stack.enter_context(patch.object(fai, 'copy', return_value=True))
            stack.enter_context(patch.object(fai, 'handoff_card'))
            stack.enter_context(patch.object(fai, 'getkey', side_effect=['h', 'q']))
            chat = stack.enter_context(patch.object(fai, 'chat_stream', return_value=iter(['Try `df -h`'])))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            fai.cmd_window(args)
            chat.assert_called_once()

    def test_error_flow_passes_captured_text_and_live_snapshot(self):
        args = SimpleNamespace(text_file=None, question='Explain this error', action='error', claude=False, paste_to=None)
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(fai, 'read_text', return_value='failed: device unavailable'))
            status = stack.enter_context(patch.object(fai, 'system_status', return_value='Failed services right now: none'))
            assistant = stack.enter_context(patch.object(fai, 'system_agent', return_value='Check the device'))
            stack.enter_context(patch.object(fai, 'header'))
            stack.enter_context(patch.object(fai, 'redraw'))
            stack.enter_context(patch.object(fai.os, 'system'))
            stack.enter_context(patch.object(fai, 'copy', return_value=True))
            stack.enter_context(patch.object(fai, 'getkey', return_value='q'))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            fai.cmd_window(args)
            status.assert_called_once()
            self.assertEqual(assistant.call_args.args[1], 'failed: device unavailable')
            self.assertEqual(assistant.call_args.kwargs['snapshot'], 'Failed services right now: none')

    def test_claude_follow_up_keeps_the_conversation(self):
        args = SimpleNamespace(text_file=None, question='what is it', action='ask', claude=True, paste_to=None)
        keys = iter(['f', 'q'])
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(fai, 'read_text', return_value='selected text'))
            for name in ('header', 'redraw', 'copy'): stack.enter_context(patch.object(fai, name))
            stack.enter_context(patch.object(fai.os, 'system'))
            stack.enter_context(patch.object(fai, 'getkey', side_effect=lambda: next(keys)))
            stack.enter_context(patch('builtins.input', return_value='and why?'))
            claude = stack.enter_context(patch.object(fai, 'claude_answer', side_effect=['first answer', 'second']))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            fai.cmd_window(args)
        follow_up = claude.call_args_list[1].args[1]
        for part in ('selected text', 'first answer', 'and why?'): self.assertIn(part, follow_up)

    def test_no_rag_sources_means_no_generated_answer(self):
        with patch.object(fai, 'search', return_value=[]), patch.object(fai, 'chat_stream') as chat:
            with contextlib.redirect_stdout(io.StringIO()): fai.cmd_rag(SimpleNamespace(question=['unknown']))
            chat.assert_not_called()

    def test_file_answer_uses_the_same_cited_context_in_terminal_and_window(self):
        hits = [(0.9, '/tmp/first.md', 'Relevant first excerpt'),
                (0.8, '/tmp/second.md', 'Relevant second excerpt')]
        with patch.object(fai, 'search', return_value=hits):
            messages, sources = fai.rag_messages('Which file?')
        self.assertEqual(sources, ['/tmp/first.md', '/tmp/second.md'])
        self.assertIn('[1] /tmp/first.md', messages[1]['content'])
        self.assertIn('[2] /tmp/second.md', messages[1]['content'])
        self.assertIn('Cite sources', messages[0]['content'])
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(fai, 'rag_messages', return_value=(messages, sources)))
            stack.enter_context(patch.object(fai, 'read_text', return_value=''))
            stack.enter_context(patch.object(fai, 'chat_stream', return_value=iter(['Answer [1].'])))
            stack.enter_context(patch.object(fai, 'copy', return_value=True))
            stack.enter_context(patch.object(fai, 'header'))
            stack.enter_context(patch.object(fai, 'redraw'))
            stack.enter_context(patch.object(fai.os, 'system'))
            stack.enter_context(patch.object(fai, 'getkey', return_value='q'))
            out = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            fai.cmd_window(SimpleNamespace(text_file=None, question='Which file?', action='rag',
                                           claude=False, paste_to=None))
            self.assertIn('[1] /tmp/first.md', out.getvalue())

    def test_file_answer_window_does_not_guess_when_index_is_empty(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(fai, 'rag_messages', return_value=([], [])))
            stack.enter_context(patch.object(fai, 'read_text', return_value=''))
            chat = stack.enter_context(patch.object(fai, 'chat_stream'))
            for name in ('header', 'redraw', 'copy'):
                stack.enter_context(patch.object(fai, name))
            stack.enter_context(patch.object(fai.os, 'system'))
            stack.enter_context(patch.object(fai, 'getkey', return_value='q'))
            out = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            fai.cmd_window(SimpleNamespace(text_file=None, question='unknown', action='rag',
                                           claude=False, paste_to=None))
            chat.assert_not_called()
            self.assertIn('No matching indexed files', out.getvalue())

class Indexing(unittest.TestCase):
    def test_fts_migration_project_scope_and_deleted_chunks(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as d, patch.object(fai, 'DATA', Path(d)):
            root = Path(d)
            first = root / 'first'; second = root / 'second'
            first.mkdir(); second.mkdir()
            one = first / 'guide.md'; two = second / 'guide.md'
            one.write_text('battery shortcut local'); two.write_text('battery shortcut foreign')
            old = fai.sqlite3.connect(root / 'index.db')
            old.execute('CREATE TABLE chunks(path TEXT, pos INT, text TEXT, vec BLOB)')
            vec = np.array([1.0, 0.0], dtype=np.float32).tobytes()
            old.executemany('INSERT INTO chunks VALUES(?,?,?,?)', [(str(one), 0, 'battery shortcut local', vec),
                                                                   (str(two), 0, 'battery shortcut foreign', vec)])
            old.commit(); old.close()
            with patch.object(fai, 'embed', return_value=[[1.0, 0.0]]):
                result = fai.search('battery shortcut', project=str(first))
                self.assertEqual([p for _, p, _ in result], [str(one)])
                con = fai.db()
                self.assertEqual(con.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'battery'").fetchone()[0], 2)
                con.execute('DELETE FROM chunks WHERE path=?', (str(one),))
                con.commit()
                self.assertEqual(fai.search('battery shortcut', project=str(first)), [])
                self.assertEqual(con.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'battery'").fetchone()[0], 1)
                con.close()

    def test_walk_excludes_sensitive_files_and_links(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(fai.CFG, search_roots=[d]):
            root = Path(d)
            for name in ['notes.md', 'tokenizer-notes.md', 'credentials.json', '.env.production.json', 'auth.json']:
                (root / name).write_text('fixture')
            (root / 'link.md').symlink_to(root / 'notes.md')
            self.assertEqual(sorted(p.name for p in fai.walk()), ['notes.md', 'tokenizer-notes.md'])

    def test_hp_ac_gate(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); bat = root / 'BAT0'; bat.mkdir()
            values = {'type':'Battery', 'status':'Discharging', 'capacity':'100', 'power_now':'0', 'energy_now':'50000000'}
            for key, value in values.items(): (bat / key).write_text(value)
            self.assertTrue(fai.index_on_ac(root, interval=0))
            (bat / 'power_now').write_text('15000000')
            self.assertFalse(fai.index_on_ac(root, interval=0))
            (bat / 'power_now').write_text('0'); (bat / 'capacity').write_text('60')
            self.assertTrue(fai.index_on_ac(root, interval=0))
            def drain(_): (bat / 'energy_now').write_text('49000000')
            with patch.object(fai.time, 'sleep', side_effect=drain):
                self.assertFalse(fai.index_on_ac(root, interval=0))



class DesktopScripts(unittest.TestCase):
    def fixture(self, root, commands):
        import os
        bindir = root / 'bin'; bindir.mkdir()
        runtime = root / 'runtime'; runtime.mkdir()
        for name, body in commands.items():
            script = bindir / name; script.write_text('#!/bin/sh\n' + body + '\n'); script.chmod(0o755)
        return {**os.environ, 'HOME': str(root), 'XDG_RUNTIME_DIR': str(runtime),
                'PATH': str(bindir) + ':' + os.environ['PATH'], 'CAPTURE': str(root / 'capture')}

    def test_selection_file_removed_after_answer_window(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            env = self.fixture(root, {'pkill':'exit 1', 'hyprctl':'''echo '{"address":"0x123"}' ''',
                'wl-paste':'printf "fixture selection"',
                'kitty':'while [ "$#" -gt 0 ]; do if [ "$1" = --text-file ]; then shift; cat "$1" > "$CAPTURE"; break; fi; shift; done'})
            menu = root / '.config/hypr/scripts/menu.sh'; menu.parent.mkdir(parents=True)
            menu.write_text('#!/bin/sh\ncat >/dev/null\ncase "$1" in *source*) printf "Selected text";; *) printf "Summarize";; esac\n'); menu.chmod(0o755)
            script = Path(__file__).resolve().parents[1] / 'config/ai/bin/ai-menu'
            subprocess.run(['bash', str(script)], env=env, check=True, capture_output=True)
            self.assertEqual((root / 'capture').read_text(), 'fixture selection')
            self.assertEqual(list((root / 'runtime').iterdir()), [])

    def test_search_opens_exact_indexed_path_even_with_display_separator(self):
        import json, subprocess, time
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            target = root / 'name   —   with separator.md'; target.write_text('fixture')
            env = self.fixture(root, {'pkill':'exit 1',
                'fai': 'printf "%s\\n" "$SEARCH_JSON"',
                'xdg-open': 'printf "%s" "$1" > "$CAPTURE"'})
            env['SEARCH_JSON'] = json.dumps([{'score': 0.9, 'path': str(target), 'snippet': 'example'}])
            menu = root / '.config/hypr/scripts/menu.sh'; menu.parent.mkdir(parents=True)
            menu.write_text('#!/bin/sh\ncat >/dev/null\ncase "$1" in Results) printf "1. result";; *) printf "query";; esac\n')
            menu.chmod(0o755)
            script = Path(__file__).resolve().parents[1] / 'config/ai/bin/ai-search'
            subprocess.run(['bash', str(script)], env=env, check=True, capture_output=True)
            for _ in range(20):
                if (root / 'capture').exists(): break
                time.sleep(0.05)
            self.assertEqual((root / 'capture').read_text(), str(target))

    def test_ocr_failure_preserves_clipboard_and_cleans_files(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            env = self.fixture(root, {'slurp':'echo "0,0 100x100"', 'grim':'exit 1',
                'tesseract':'echo eng', 'wl-copy':'cat > "$CAPTURE"', 'notify-send':'exit 0'})
            script = Path(__file__).resolve().parents[1] / 'config/ai/bin/ai-ocr'
            result = subprocess.run(['bash', str(script)], env=env, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertFalse((root / 'capture').exists())
            self.assertEqual(list((root / 'runtime').iterdir()), [])

    def test_stale_dictation_pid_is_not_a_recording(self):
        import json, os, subprocess
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); env = self.fixture(root, {})
            (root / 'runtime/dictate.pid').write_text(str(os.getpid()))
            script = Path(__file__).resolve().parents[1] / 'config/ai/bin/ai-dictate'
            result = subprocess.run(['bash', str(script), 'status'], env=env, check=True, capture_output=True, text=True)
            self.assertEqual(json.loads(result.stdout)['class'], 'idle')


class TerminalHelpers(unittest.TestCase):
    def test_why_preserves_the_previous_command(self):
        import subprocess
        script = Path(__file__).resolve().parents[1] / 'config/ai/zsh-ai.zsh'
        result = subprocess.run(['zsh', '-f', '-c',
            'source "$1"; _fai_preexec "false"; _fai_last_status=1; _fai_preexec "why"; print -r -- "${_fai_last_cmd}:${_fai_last_status}"',
            'test', str(script)], check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), 'false:1')


class SpeechCleanup(unittest.TestCase):
    def test_voice_question_captures_one_phrase_and_stops_on_pause(self):
        import numpy as np
        spec = importlib.util.spec_from_file_location('voice_ask', Path(__file__).resolve().parents[1] / 'config/ai/voice-ask.py')
        voice = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(voice)
        rate = voice.speech.RATE
        tone = (np.sin(2 * np.pi * 440 * np.arange(rate) / rate) * 6000).astype(np.int16)
        samples = np.concatenate([np.zeros(rate // 2, dtype=np.int16), tone,
                                  np.zeros(rate * 2, dtype=np.int16)])
        with tempfile.TemporaryDirectory() as d:
            pcm = Path(d) / 'question.pcm'; pcm.write_bytes(samples.tobytes())
            captured = voice.capture(['cat', str(pcm)])
        self.assertGreater(len(captured), rate)
        self.assertLess(len(captured), len(samples.tobytes()))

    def test_voice_questions_route_to_system_or_grounded_files(self):
        spec = importlib.util.spec_from_file_location('voice_ask', Path(__file__).resolve().parents[1] / 'config/ai/voice-ask.py')
        voice = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(voice)
        self.assertEqual(voice.route_question('Why is Wi-Fi off?'), ('system', 'Why is Wi-Fi off?'))
        self.assertEqual(voice.route_question('Ask using my files about the backup'), ('rag', 'the backup'))
        self.assertEqual(voice.route_question('Ask about my clipboard why does it fail'), ('clipboard', 'why does it fail'))

    def test_silent_eof_cleans_pid_without_real_service_stop(self):
        spec = importlib.util.spec_from_file_location('dictate', Path(__file__).resolve().parents[1] / 'config/ai/dictate-live.py')
        dictate = importlib.util.module_from_spec(spec); spec.loader.exec_module(dictate)
        with tempfile.TemporaryDirectory() as d, contextlib.ExitStack() as stack:
            root = Path(d)
            stack.enter_context(patch.object(dictate, 'PIDF', root / 'dictate.pid'))
            stack.enter_context(patch.dict(dictate.os.environ, DICTATE_TEST_PCM=str(root / "sample's audio.pcm")))
            stack.enter_context(patch.object(dictate.signal, 'signal'))
            stack.enter_context(patch.object(dictate, 'notify'))
            stack.enter_context(patch.object(dictate.subprocess, 'run'))
            from unittest.mock import Mock
            recorder = SimpleNamespace(stdout=io.BytesIO(bytes(16000*2)), terminate=Mock())
            launch = stack.enter_context(patch.object(dictate.subprocess, 'Popen', return_value=recorder))
            transcribe = stack.enter_context(patch.object(dictate, 'transcribe'))
            dictate.main()
            self.assertFalse((root / 'dictate.pid').exists())
            transcribe.assert_not_called()
            recorder.terminate.assert_called_once()
            calls = launch.call_args_list
            self.assertEqual(calls[0].args[0][:2], ['cat', '--'])
            self.assertEqual(len(calls), 1)  # direct test runs must not schedule a real service stop

    def test_late_phrase_never_types_into_another_window(self):
        spec = importlib.util.spec_from_file_location('dictate', Path(__file__).resolve().parents[1] / 'config/ai/dictate-live.py')
        dictate = importlib.util.module_from_spec(spec); spec.loader.exec_module(dictate)
        for focus, locked, typed in [('0xA', False, True), ('0xB', False, False), ('0xA', True, False)]:
            calls = []
            def run(cmd, **kw):
                calls.append(cmd)
                if cmd[0] == 'hyprctl': return SimpleNamespace(stdout='{"address": "%s"}' % focus, returncode=0)
                if cmd[0] == 'pgrep': return SimpleNamespace(returncode=0 if locked else 1)
                return SimpleNamespace(returncode=0, stdout='')
            state = {'first': True, 'typed': '', 'held': '', 'target': '0xA'}
            with self.subTest(focus=focus, locked=locked), patch.object(dictate.subprocess, 'run', side_effect=run), patch.object(dictate, 'notify'):
                dictate.emit('hello world', state)
                self.assertEqual(any(c[0] == 'wtype' for c in calls), typed)
                self.assertEqual(state['held'], '' if typed else 'hello world')


class Launcher(unittest.TestCase):
    def test_rofi_skips_dbus_activation(self):
        # rofi gives D-Bus activation 1.5 s, then also runs Exec: slow cold starts opened Files twice.
        rasi = (Path(__file__).resolve().parents[1] / 'config/rofi/config.rasi').read_text()
        self.assertIn('drun { DBusActivatable: false; }', rasi)

if __name__ == '__main__': unittest.main()
