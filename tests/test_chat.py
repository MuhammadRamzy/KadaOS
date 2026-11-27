"""Offline checks for AI Chat logic (no GTK window, no network, no model)."""
import importlib.util, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('chat', Path(__file__).resolve().parents[1] / 'config/ai/chat.py')
chat = importlib.util.module_from_spec(spec); spec.loader.exec_module(chat)


class Web(unittest.TestCase):
    def test_current_questions_trigger_web(self):
        for q in ['latest kernel version', 'news today', 'price of RTX 5090', 'what happened in 2026']:
            self.assertTrue(chat.needs_web(q), q)
        for q in ['explain recursion', 'write a bash loop']:
            self.assertFalse(chat.needs_web(q), q)

    def test_html_text_drops_scripts_and_nav(self):
        page = '<html><nav>Menu</nav><script>evil()</script><p>Real   text</p><footer>f</footer></html>'
        self.assertEqual(chat.html_to_text(page), 'Real text')

    def test_failed_page_falls_back_to_snippet_and_sources_are_numbered(self):
        results = [{'title': 'A', 'url': 'https://a', 'snippet': 'snip A', 'date': '2026-11-01'},
                   {'title': 'B', 'url': 'https://b', 'snippet': 'snip B', 'date': ''}]
        def fetch(url):
            if url == 'https://a': raise OSError('timeout')
            return 'body B'
        ctx, src = chat.web_context('q', search=lambda q: results, fetch=fetch)
        self.assertIn('[1] A — https://a (published 2026-11-01)\nsnip A', ctx)
        self.assertIn('[2] B — https://b\nbody B', ctx)
        self.assertEqual(src, results)


class Conversation(unittest.TestCase):
    def test_prompt_states_web_situation(self):
        self.assertIn('cite like [1]', chat.system_prompt(True))
        self.assertIn('may be outdated', chat.system_prompt(False))
        self.assertIn('Web search failed (no results)', chat.system_prompt(False, 'no results'))

    def test_history_trimmed_newest_kept_and_web_on_last_turn(self):
        hist = [{'role': 'user', 'content': 'x' * 9000}, {'role': 'assistant', 'content': 'y' * 9000},
                {'role': 'user', 'content': 'now', 'context': 'file body'}]
        msgs = chat.build_messages(hist, web_ctx='[1] src')
        self.assertEqual(msgs[0]['role'], 'system')
        self.assertEqual(len(msgs), 3)  # oldest dropped
        self.assertTrue(msgs[-1]['content'].startswith('<web>\n[1] src'))
        self.assertIn('<attached>\nfile body', msgs[-1]['content'])

    def test_markdown_is_escaped_and_code_split(self):
        self.assertEqual(chat.md_to_markup('**a** <b> `c`'), '<b>a</b> &lt;b&gt; <tt>c</tt>')
        self.assertIn('<a href="https://x.org">t</a>', chat.md_to_markup('[t](https://x.org)'))
        blocks = chat.split_blocks('hi\n```py\nprint(1)\n```\nbye\n```sh\nunclosed')
        self.assertEqual(blocks, [('text', 'hi'), ('code:py', 'print(1)'), ('text', 'bye'), ('code:sh', 'unclosed')])

    def test_attachments_refuse_images_and_binaries(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'a.png').write_bytes(b'x'); (Path(d) / 'b.bin').write_bytes(b'\0\1\2')
            (Path(d) / 'c.txt').write_text('hello')
            self.assertIn('images', chat.read_attachment(Path(d) / 'a.png')[1])
            self.assertIn('binary', chat.read_attachment(Path(d) / 'b.bin')[1])
            self.assertEqual(chat.read_attachment(Path(d) / 'c.txt'), ('hello', ''))
            self.assertTrue(chat.read_attachment(Path(d) / 'missing.txt')[1])

    def test_store_roundtrip_skips_damaged_files(self):
        with tempfile.TemporaryDirectory() as d:
            s = chat.Store(Path(d)); c = s.new(); c['messages'].append({'role': 'user', 'content': 'hi'}); s.save(c)
            (Path(d) / 'broken.json').write_text('{oops')
            self.assertEqual([x['id'] for x in s.all()], [c['id']])
            s.delete(c); self.assertEqual(s.all(), [])

    def test_searx_missing_container_message(self):
        with patch.object(chat, 'searx_up', return_value=False), \
             patch.object(chat.subprocess, 'run', return_value=type('R', (), {'returncode': 1, 'stderr': 'Error: No such container: searxng'})()):
            ok, started, msg = chat.ensure_searx()
        self.assertFalse(ok); self.assertIn('install-search.sh', msg)




class Agent(unittest.TestCase):
    def test_table_parsing(self):
        rows = chat.parse_table(['| A | B |', '|---|---|', '| 1 | 2 |', '| 3 | 4 |'])
        self.assertEqual(rows, [['A', 'B'], ['1', '2'], ['3', '4']])
        self.assertIsNone(chat.parse_table(['| A | B |', 'not a sep', '| 1 | 2 |']))

    def test_split_text_and_tables(self):
        segs = chat.split_text_and_tables("intro\n\n| X | Y |\n|---|---|\n| 1 | 2 |\n\nouttro")
        kinds = [k for k, _ in segs]
        self.assertEqual(kinds, ['text', 'table', 'text'])
        self.assertEqual(segs[1][1][0], ['X', 'Y'])

    def test_desktop_action_allowlist(self):
        ran = []
        self.assertEqual(chat.run_agent_tool('desktop_action', {'action': 'night_light'}, run=ran.append)[1], True)
        self.assertIn('nightlight.sh', ran[0])
        self.assertIn('unknown action', chat.run_agent_tool('desktop_action', {'action': 'rm -rf /'}, run=ran.append)[0])

    def test_open_app_quotes(self):
        ran = []
        chat.run_agent_tool('open_app', {'name': 'firefox'}, run=ran.append)
        self.assertIn('gtk-launch firefox', ran[0])

    def test_agent_messages_include_system_and_history(self):
        hist = [{'role': 'user', 'content': 'hi'}, {'role': 'assistant', 'content': 'hello'}, {'role': 'user', 'content': 'now'}]
        msgs = chat.agent_messages(hist)
        self.assertEqual(msgs[0]['role'], 'system')
        self.assertIn('KadaOS', msgs[0]['content'])
        self.assertEqual([m['role'] for m in msgs[1:]], ['user', 'assistant', 'user'])


class Controls(unittest.TestCase):
    def test_show_control_tool_and_allowlist(self):
        self.assertIn('brightness', chat.CONTROLS)
        with patch.object(chat, 'control_state', return_value=31):
            out, _ = chat.run_agent_tool('show_control', {'control': 'brightness'})
        self.assertIn('Current real value: 31%', out)        # the model gets the real reading, not a guess
        with patch.object(chat, 'control_state', return_value=None):
            self.assertIn('Current real value: unknown', chat.run_agent_tool('show_control', {'control': 'brightness'})[0])
        self.assertIn('unknown control', chat.run_agent_tool('show_control', {'control': 'hack'})[0])

    def test_control_apply_commands(self):
        import unittest.mock as mock
        with mock.patch.object(chat.subprocess, 'Popen') as pop:
            self.assertEqual(chat.control_apply('brightness', 42), 'brightnessctl set 42%')
            self.assertEqual(chat.control_apply('volume', 30), 'wpctl set-volume @DEFAULT_AUDIO_SINK@ 30%')
            self.assertEqual(chat.control_apply('wifi', True), 'nmcli radio wifi on')
            self.assertEqual(chat.control_apply('wifi', False), 'nmcli radio wifi off')
            self.assertEqual(chat.control_apply('power_mode', 'performance'), 'powerprofilesctl set performance')
            self.assertTrue(pop.called)


class DoAnything(unittest.TestCase):
    def test_run_command_needs_approval_and_refuses_sudo(self):
        with tempfile.TemporaryDirectory() as d:
            mark = Path(d) / 'ran'
            cmd = {'command': f'touch {mark}', 'reason': 'test'}
            self.assertIn('declined', chat.run_agent_tool('run_command', cmd)[0])            # no UI → declined
            self.assertIn('declined', chat.run_agent_tool('run_command', cmd, confirm=lambda *a: False)[0])
            self.assertFalse(mark.exists())
            out, did = chat.run_agent_tool('run_command', cmd, confirm=lambda *a: True)
            self.assertTrue(mark.exists() and did and out.startswith('exit 0'))
        # sudo becomes an admin request: approval card, then pkexec (stubbed here, never run for real)
        asked, ran = [], []
        with patch.object(chat, 'run_capture', side_effect=lambda argv, *a, **k: ran.append(argv) or (0, 'ok')):
            out, did = chat.run_agent_tool('run_command', {'command': 'sudo apt install x', 'reason': ''},
                                           confirm=lambda *a: asked.append(a) or True)
            self.assertEqual(ran[0], ['pkexec', 'bash', '-c', 'set -o pipefail; apt install x'])
            self.assertEqual(asked[0][0], 'Run as administrator?'); self.assertIsNone(asked[0][3])   # admin: never "always"
            ran.clear()
            self.assertIn('declined', chat.run_agent_tool('run_command', {'command': 'apt list', 'admin': True, 'reason': ''})[0])
            self.assertEqual(ran, [])

    def test_always_allow_only_simple_safe_commands(self):
        self.assertEqual(chat.allow_key('mkdir -p ~/x'), 'mkdir')
        self.assertEqual(chat.allow_key('hyprctl dispatch workspace 2'), 'hyprctl')
        for bad in ['mkdir x && rm -rf ~', 'echo hi > f', 'rm -rf x', 'ls $(whoami)', 'bash -c ls', 'cat a | sh']:
            self.assertIsNone(chat.allow_key(bad), bad)
        with tempfile.TemporaryDirectory() as d, patch.object(chat, 'ALLOW', Path(d) / 'allow.json'), \
             patch.object(chat, 'run_capture', return_value=(0, 'done')):
            ans = iter(['always'])
            chat.run_agent_tool('run_command', {'command': 'playerctl next', 'reason': ''}, confirm=lambda *a: next(ans))
            self.assertEqual(chat.allowed(), {'playerctl'})
            out, _ = chat.run_agent_tool('run_command', {'command': 'playerctl play-pause', 'reason': ''})   # no confirm needed now
            self.assertTrue(out.startswith('exit 0'))
            self.assertIn('declined', chat.run_agent_tool('run_command', {'command': 'playerctl next; rm -rf x', 'reason': ''})[0])

    def test_calculate_is_exact_and_safe(self):
        self.assertEqual(chat.calculate('17% * 2,340'), '397.8')
        self.assertEqual(chat.calculate('(1200-350)/4'), '212.5')
        with self.assertRaises(ValueError): chat.calculate('__import__("os").system("id")')

    def test_file_action_validates_and_converts(self):
        self.assertIsNotNone(chat.FA)
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'a.png'
            from PIL import Image; Image.new('RGB', (40, 30)).save(src)
            self.assertIn('not found', chat.run_agent_tool('file_action', {'action': 'img_convert', 'paths': [f'{d}/nope.png']})[0])
            self.assertIn('does not apply', chat.run_agent_tool('file_action', {'action': 'pdf_merge', 'paths': [str(src)]})[0])
            self.assertIn('option must be', chat.run_agent_tool('file_action', {'action': 'img_convert', 'paths': [str(src)], 'option': 'exe'})[0])
            out, did = chat.run_agent_tool('file_action', {'action': 'img_convert', 'paths': [str(src)], 'option': 'webp'})
            self.assertTrue(did, out); self.assertTrue(list(Path(d).glob('*.webp')))

    def test_recipes_match_seclab_and_need_approval(self):
        self.assertEqual(chat.RECIPES, list(chat.SECLAB.RECIPES))
        ran = []
        with patch.object(chat.SECLAB, 'active', return_value=None):
            out, _ = chat.run_agent_tool('security_recipe', {'recipe': 'nmap-quick', 'target': '127.0.0.1'}, run=ran.append)
        self.assertIn('declined', out); self.assertEqual(ran, [])

    def test_layout_is_quoted_data(self):
        ran = []
        chat.run_agent_tool('start_layout', {'request': "coding; rm -rf ~"}, run=ran.append)
        self.assertIn("-- 'coding; rm -rf ~'", ran[0])

    def test_steps_feed_back_into_history(self):
        hist = [{'role': 'user', 'content': 'scan'},
                {'role': 'assistant', 'content': 'found 2', 'steps': [{'tool': 'security_recipe', 'label': 'lan-discover on x',
                                                                         'status': 'done', 'out': 'Host 192.168.1.7 is up'}]},
                {'role': 'user', 'content': 'show the output'}]
        msgs = chat.agent_messages(hist)
        roles = [m['role'] for m in msgs]
        self.assertEqual(roles, ['system', 'user', 'assistant', 'tool', 'assistant', 'user'])   # native tool replay
        self.assertEqual(msgs[2]['tool_calls'][0]['function']['name'], 'security_recipe')
        self.assertIn('Host 192.168.1.7 is up', msgs[3]['content'])
        self.assertNotIn('tool_results', ''.join(m['content'] for m in msgs))
        self.assertIn('NEVER invent', msgs[0]['content'])

    def test_set_scope_needs_authorization(self):
        with tempfile.TemporaryDirectory() as d, patch.object(chat.SECLAB, 'ENG_ROOT', Path(d) / 'e'), \
             patch.object(chat.SECLAB, 'ACTIVE', Path(d) / 'active'):
            args = {'engagement': 'home-network', 'targets': ['192.168.1.0/24']}
            self.assertIn('did not authorize', chat.run_agent_tool('set_scope', args, confirm=lambda *a: False)[0])
            self.assertIsNone(chat.SECLAB.active())
            out, did = chat.run_agent_tool('set_scope', args, confirm=lambda *a: True)
            self.assertTrue(did); self.assertEqual(chat.SECLAB.scope(chat.SECLAB.active()), ['192.168.1.0/24'])

    def test_run_capture_stop_and_status(self):
        import threading
        ev = threading.Event(); threading.Timer(0.3, ev.set).start()
        code, out = chat.run_capture(['bash', '-c', 'echo hi; sleep 30'], cancel=ev)
        self.assertEqual(code, -1); self.assertIn('hi', out)
        self.assertEqual(chat.step_status('exit 0\nok'), 'done')
        self.assertEqual(chat.step_status('exit 2\nboom'), 'failed')
        self.assertEqual(chat.step_status('the user declined'), 'declined')


class Voice(unittest.TestCase):
    def test_speakable_keeps_prose_only(self):
        t = "**Done.** See [docs](https://x.y/z).\n\n```bash\nrm -rf /\n```\n| a | b |\n|---|---|\n- `ls` works"
        self.assertEqual(chat.speakable(t), "Done. See docs. ls works")

    def test_sentences_stream_as_they_complete(self):
        f = chat.SentenceFeeder()
        got = []
        for tok in ["Your battery", " is at 52%. It", "'s charging", ". Code:\n```sh\necho hi.", " more.\n```\nAll good"]:
            got += f.feed(tok)
        got += f.flush()
        self.assertEqual(got, ["Your battery is at 52%.", "It's charging.", "Code:", "All good"])

    def test_long_answers_are_capped(self):
        f = chat.SentenceFeeder(limit=40)
        out = f.feed("First sentence is fine. Second sentence is much too long to say aloud. Third. ") + f.flush()
        self.assertEqual(out, ["First sentence is fine.", "The rest is on screen."])

    def test_voice_send_without_server_is_harmless(self):
        with patch.object(chat, 'VOICE_SOCK', Path('/nonexistent/sock')):
            self.assertIsNone(chat.voice_send({'stop': True}, start=False))


class SettingsControls(unittest.TestCase):
    def test_settings_words_show_controls(self):
        self.assertEqual(chat.detect_controls("i need to setup all my display settings like brightness, night light and power mode"),
                         ["brightness", "night_light", "power_mode"])
        self.assertEqual(chat.detect_controls("make it a bit louder"), ["volume"])
        self.assertEqual(chat.detect_controls("turn off wifi and bluetooth"), ["wifi", "bluetooth"])
        self.assertEqual(chat.detect_controls("what's the capital of Kerala"), [])

    def test_controls_reach_ui_first_with_real_values(self):
        with patch.object(chat, 'control_state', return_value=30), patch.object(chat.fai, 'ensure_server'), \
             patch.object(chat.fai, '_req', side_effect=RuntimeError('stop after setup')):
            gen = chat.agent_stream([{'role': 'user', 'content': 'set my brightness'}])
            self.assertEqual(next(gen), ('control', 'brightness'))
            with self.assertRaises(RuntimeError): next(gen)


if __name__ == '__main__': unittest.main()


class ContextAndWindows(unittest.TestCase):
    CLIENTS = [{'class': 'org.myos.Chat', 'focusHistoryID': 0, 'address': '0xc', 'pid': 1},
               {'class': 'firefox', 'title': 'Docs', 'focusHistoryID': 2, 'address': '0xf', 'pid': 2},
               {'class': 'kitty', 'title': 'zsh ~/proj', 'focusHistoryID': 1, 'address': '0xk', 'pid': 3}]

    def test_user_window_skips_the_chat_itself(self):
        self.assertEqual(chat.user_window(self.CLIENTS)['class'], 'kitty')
        self.assertIsNone(chat.user_window([self.CLIENTS[0]]))

    def test_shell_cwds_walks_the_terminal_tree(self):
        with tempfile.TemporaryDirectory() as d:
            proc = Path(d)
            def mk(pid, ppid, comm, cwd=None):
                (proc / str(pid)).mkdir(); (proc / str(pid) / 'stat').write_text(f'{pid} ({comm}) S {ppid} 0')
                (proc / str(pid) / 'comm').write_text(comm + '\n')
                if cwd: (proc / str(pid) / 'cwd').symlink_to(cwd)
            mk(10, 1, 'term'); mk(11, 10, 'agent'); mk(12, 11, 'zsh', d); mk(13, 11, 'zsh', '/'); mk(14, 12, 'vim', '/')
            self.assertEqual(chat.shell_cwds(10, proc), ['/', str(proc.resolve())])

    def test_window_dispatch_targets_and_validates(self):
        with patch.object(chat, '_hypr_json', return_value=self.CLIENTS):
            self.assertEqual(chat.window_dispatch('focus', 'Docs'), [['hyprctl', 'dispatch', 'focuswindow', 'address:0xf']])
            self.assertEqual(chat.window_dispatch('move_to_workspace', '', '3'),
                             [['hyprctl', 'dispatch', 'movetoworkspacesilent', '3,address:0xk']])
            for bad in [('focus', 'nothing-open', ''), ('switch_workspace', '', '1; rm -rf ~'), ('maximize', '', '')]:
                with self.assertRaises(ValueError): chat.window_dispatch(*bad)

    def test_close_needs_approval_and_text_only_on_request(self):
        with patch.object(chat, '_hypr_json', return_value=self.CLIENTS), patch.object(chat, 'run_capture') as rc:
            self.assertIn('declined', chat.run_agent_tool('window', {'action': 'close'})[0])
            rc.assert_not_called()
            rc.return_value = (0, 'ok')
            self.assertEqual(chat.run_agent_tool('window', {'action': 'close'}, confirm=lambda *a: True), ('done: close', True))
        with patch.object(chat, '_hypr_json', side_effect=lambda w: self.CLIENTS if w == 'clients' else {'id': 1}), \
             patch.object(chat, '_q', return_value='') as q:
            chat.gather_context(False)
            self.assertFalse(any('wl-paste' in c.args for c in q.call_args_list))


class MemoryLogRoutines(unittest.TestCase):
    def test_memory_saves_dedupes_scopes_and_forgets(self):
        with tempfile.TemporaryDirectory() as d:
            db = f'{d}/m.db'; fake = lambda texts, kind='document': [[1.0, 0.0] for _ in texts]
            self.assertIn('remembered', chat.remember('The user prefers pnpm.', embed=fake, db_path=db))
            self.assertEqual(chat.remember('The user  prefers pnpm.', embed=fake, db_path=db), 'already remembered')
            chat.remember('Acme uses Next.js.', '/p/acme', embed=fake, db_path=db)
            self.assertEqual(chat.relevant_memories('q', (), embed=fake, db_path=db), ['The user prefers pnpm.'])
            self.assertEqual(len(chat.relevant_memories('q', ('/p/acme',), embed=fake, db_path=db)), 2)
            fid, text = chat.find_memory('pnpm please', db_path=db)
            self.assertEqual(text, 'The user prefers pnpm.'); chat.forget(fid, db_path=db)
            self.assertEqual([m[1] for m in chat.memories(db_path=db)], ['Acme uses Next.js.'])
            self.assertIsNone(chat.find_memory('zebra', db_path=db))

    def test_memory_ranks_by_meaning_when_many(self):
        with tempfile.TemporaryDirectory() as d:
            db = f'{d}/m.db'
            vec = lambda t: [1.0, 0.0] if 'coffee' in t else [0.0, 1.0]
            fake = lambda texts, kind='document': [vec(t) for t in texts]
            for i in range(10): chat.remember(f'fact {i}', embed=fake, db_path=db)
            chat.remember('The user drinks black coffee.', embed=fake, db_path=db)
            self.assertEqual(chat.relevant_memories('coffee?', k=1, embed=fake, db_path=db), ['The user drinks black coffee.'])

    def test_action_log_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            chat.log_action('media', {'action': 'next'}, 'done', path=f'{d}/l.jsonl')
            self.assertEqual(chat.recent_actions(path=f'{d}/l.jsonl')[0]['label'], 'media: next')
            self.assertEqual(chat.recent_actions(path=f'{d}/none.jsonl'), [])

    def test_slash_commands(self):
        self.assertEqual(chat.parse_slash('/scan 192.168.1.0/24'), ('prompt', 'Run a security scan of 192.168.1.0/24'))
        self.assertEqual(chat.parse_slash('/memory'), ('local', 'memory', ''))
        self.assertEqual(chat.parse_slash('/remember I like tea'), ('local', 'remember', 'I like tea'))
        self.assertEqual(chat.parse_slash('/nope'), ('local', 'help', 'nope'))
        self.assertEqual(chat.parse_slash('/layout'), ('local', 'help', ''))
        self.assertIsNone(chat.parse_slash('what is /etc/hosts'))

    def test_media_reports_real_player_state(self):
        calls = []
        def run(argv):
            calls.append(argv); return (0, 'Playing: A — B (spotify)') if 'metadata' in argv else (0, '')
        with patch.object(chat.time, 'sleep'):
            self.assertEqual(chat.media('next', run), ('done: next; now: Playing: A — B (spotify)', True))
        self.assertEqual(calls[0], ['playerctl', 'next'])
        self.assertFalse(chat.media('rm', run)[1])
        with patch.object(chat, 'media', return_value=('ok', True)) as m:
            chat.run_agent_tool('media', {'action': 'skip'}); m.assert_called_with('next')
        with patch.object(chat, 'remember', return_value='remembered') as r:
            chat.run_agent_tool('remember', {'about': 'The user prefers pnpm.'}); r.assert_called_with('The user prefers pnpm.', '')
        self.assertIn('no media player', chat.media('next', lambda a: (1, 'No players found'))[0])

    def test_capture_cuts_out_the_chat_panel(self):
        win = {'at': [0, 40], 'size': [1900, 1000], 'workspace': {'id': 1}}
        self.assertEqual(chat.capture_rect(win, {'at': [1480, 40], 'size': [420, 900], 'workspace': {'id': 1}}), (0, 40, 1480, 1000))
        self.assertEqual(chat.capture_rect(win, {'at': [1480, 40], 'size': [420, 900], 'workspace': {'id': 2}}), (0, 40, 1900, 1000))
        self.assertEqual(chat.capture_rect(win, None), (0, 40, 1900, 1000))

    def test_routine_units_and_names(self):
        self.assertEqual(chat.routine_name('Morning Brief!'), 'morning-brief')
        with self.assertRaises(ValueError): chat.routine_name('!!!')
        svc, tmr = chat.routine_units('morning-brief', 'Mon..Fri 09:00')
        self.assertIn('chat.py --routine morning-brief', svc); self.assertIn('OnCalendar=Mon..Fri 09:00', tmr)
        with self.assertRaises(ValueError): chat.check_calendar('every tuesday-ish')
        self.assertTrue(chat.check_calendar('Mon..Fri 09:00'))

    def test_schedule_needs_approval(self):
        with patch.object(chat, 'add_routine') as add:
            self.assertIn('declined', chat.run_agent_tool('schedule_routine', {'name': 'x', 'when': 'daily', 'prompt': 'hi'})[0])
            add.assert_not_called()

    def test_recent_files_from_xbel(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / 'a.txt', Path(d) / 'b c.txt'; a.write_text('1'); b.write_text('2')
            x = Path(d) / 'r.xbel'
            x.write_text(f'<xbel><bookmark href="file://{a}" modified="2026-01-01T00:00:00Z"/>'
                         f'<bookmark href="file://{str(b).replace(" ", "%20")}" modified="2026-02-01T00:00:00Z"/>'
                         f'<bookmark href="file:///gone" modified="2026-03-01T00:00:00Z"/></xbel>')
            self.assertEqual(chat.recent_files(xbel=x), [str(b), str(a)])


wspec = importlib.util.spec_from_file_location('watch', Path(__file__).resolve().parents[1] / 'config/ai/watch.py')
watch = importlib.util.module_from_spec(wspec); wspec.loader.exec_module(watch)


class Watchers(unittest.TestCase):
    def test_problems_and_dedupe(self):
        from collections import namedtuple
        DU = namedtuple('DU', 'total used free')
        ok = dict(disk=DU(500e9, 100e9, 400e9), bat=(80, 'Discharging'), failed=[], gpu_temp=50, cpu_temp=60, evs=[], now=0, remote={})
        self.assertEqual(watch.problems(**ok), {})
        bad = watch.problems(disk=DU(500e9, 490e9, 10e9), bat=(9, 'Discharging'), failed=['foo.service'], gpu_temp=90, cpu_temp=60, evs=[], remote={})
        self.assertEqual(set(bad), {'disk', 'battery', 'failed:foo.service', 'gpu-hot'})
        self.assertNotIn('battery', watch.problems(**{**ok, 'bat': (9, 'Charging')}))
        evs = [(600, 'Standup', 'Work', False), (5000, 'Later', 'Work', False), (300, 'Holiday', 'Work', True)]
        self.assertEqual([v[0] for v in watch.problems(**{**ok, 'evs': evs}).values()], ['In 10 min: Standup'])
        state = {}
        self.assertEqual(len(watch.due(bad, state, 1000)), 4)
        self.assertEqual(watch.due(bad, state, 2000), {})                 # no repeat within 6 h
        self.assertEqual(len(watch.due(bad, state, 1000 + watch.REPEAT)), 4)
        watch.due({}, state, 99999); self.assertEqual(state, {})          # resolved problems are forgotten


class RemoteTool(unittest.TestCase):
    def test_argv_validation(self):
        self.assertEqual(chat.remote_argv('status', board='B'), ['B', 'json', 'status'])
        self.assertEqual(chat.remote_argv('run', '@lab', 'uptime', board='B'), ['B', 'run', '@lab', '--', 'uptime'])
        for bad in [('info', ''), ('info', 'pi;rm'), ('start_job', '@lab', 'x'), ('run', 'pi', ' '), ('job_log', '', '', '', '; rm'),
                    ('logs', 'pi', '', 'x; rm -rf ~'), ('format_disk', 'pi')]:
            with self.assertRaises(ValueError, msg=bad): chat.remote_argv(*bad, board='B')

    def test_runs_board_and_asks_before_changes(self):
        with tempfile.TemporaryDirectory() as d:
            b = Path(d) / '.local/bin/board'; b.parent.mkdir(parents=True)
            log = Path(d) / 'calls'
            b.write_text(f'#!/bin/sh\necho "$@" >> {log}\n'
                         'case "$1" in json) echo \'{"pi5": {"state": "online", "via": "Wi-Fi", "temp_c": 51.2, "throttled": ["under-voltage now"]}, '
                         '"zero": {"state": "offline"}}\';; *) echo ran;; esac\n')
            b.chmod(0o755)
            old = chat.HOME; chat.HOME = Path(d)
            try:
                out, did = chat.run_agent_tool('remote', {'action': 'status'})
                self.assertIn('pi5: online · via Wi-Fi · 51°C · power: under-voltage now', out); self.assertFalse(did)
                self.assertIn('zero: offline', out)
                self.assertIn('declined', chat.run_agent_tool('remote', {'action': 'reboot', 'device': 'pi5'})[0])   # no UI
                asked = []
                out, did = chat.run_agent_tool('remote', {'action': 'run', 'device': 'pi5', 'command': 'uptime'},
                                               confirm=lambda *a: asked.append(a) or True)
                self.assertTrue(did); self.assertEqual(asked[0][1], 'uptime')
                self.assertEqual(log.read_text().splitlines(), ['json status', 'run pi5 -- uptime'], 'declined reboot never ran')
            finally:
                chat.HOME = old

    def test_watcher_formats_jobs(self):
        with tempfile.TemporaryDirectory() as d:
            b = Path(d) / 'board'
            b.write_text('#!/bin/sh\ncase "$1" in watch) echo \'{"dev-hot:pi": ["pi running hot", "83 C."]}\';; '
                         'job) echo \'{"0101-000000-aaaa": {"device": "pi", "cmd": "make", "state": "done", "rc": 2, "tail": ["error: x"]}}\';; esac\n')
            b.chmod(0o755)
            got = watch.remote_problems(board=b, phone=Path(d) / 'no-phone')
            self.assertEqual(got['dev-hot:pi'], ('pi running hot', '83 C.'))
            self.assertEqual(got['job:0101-000000-aaaa'], ('✗ Job failed (exit 2) on pi', '$ make\nerror: x'))
            self.assertEqual(watch.remote_problems(board=Path(d) / 'missing', phone=Path(d) / 'no-phone'), {})


class SlashAutocomplete(unittest.TestCase):
    def test_commands_filter_and_mark_arguments(self):
        all_ = chat.slash_suggestions('/')
        self.assertEqual(len(all_), len(chat.SLASH_HELP))
        self.assertEqual(chat.slash_suggestions('/me'), [('/memory', '/memory', chat.SLASH_HELP[0][1], True)])
        self.assertEqual(chat.slash_suggestions('/sc')[0][0], '/scan ')            # takes a target: not ready yet
        self.assertFalse(chat.slash_suggestions('/sc')[0][3])
        self.assertEqual(chat.slash_suggestions('/zzz'), [])
        self.assertEqual(chat.slash_suggestions('hello /me'), [])
        self.assertEqual(chat.slash_suggestions('/remember I like'), [])

    def test_arguments_are_suggested(self):
        self.assertEqual([s[0] for s in chat.slash_suggestions('/layout w', layouts=['Coding', 'Web dev'])], ['/layout Web dev'])
        self.assertEqual([s[0] for s in chat.slash_suggestions('/scan 10', scope=['10.0.0.0/24', 'example.com'])], ['/scan 10.0.0.0/24'])
        conv = chat.slash_suggestions('/convert rep', recent=['/home/u/report.pdf', '/home/u/cat.png'])
        self.assertEqual(conv, [('/convert /home/u/report.pdf to ', 'report.pdf', '/home/u', False)])
        self.assertEqual(chat.slash_suggestions('/convert a.pdf to png', recent=['/x/a.pdf']), [])


class SmartActions(unittest.TestCase):
    def test_actions_for_real_paths_links_and_commands(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d) / 'acme'; (proj / '.git').mkdir(parents=True); f = proj / 'app.py'; f.write_text('x')
            have = lambda prog: '/usr/bin/' + prog
            text = (f'The project is at **{proj}**. Main file: `{f}`. Docs: https://www.example.com/docs. '
                    f'Missing: {d}/nope.\n```bash\n$ git status\n```')
            acts = [(k, v) for _l, _i, k, v in chat.suggest_actions(text, have=have)]
            self.assertEqual(acts[:3], [('folder', str(proj)), ('vscode', str(proj)), ('terminal', str(proj))])
            self.assertIn(('open', str(f)), acts); self.assertIn(('vscode', str(f)), acts)
            self.assertIn(('link', 'https://www.example.com/docs'), acts)
            self.assertIn(('run', 'git status'), acts)
            self.assertFalse(any(v.endswith('nope') for _k, v in acts))
            labels = [l for l, *_ in chat.suggest_actions(text, have=have)]
            self.assertEqual(labels[0], 'Open acme')                  # a git folder is named as the project
            self.assertNotIn(('vscode', str(proj)), [(k, v) for _l, _i, k, v in chat.suggest_actions(text, have=lambda p: None)])

    def test_no_actions_for_plain_text(self):
        self.assertEqual(chat.suggest_actions('All done. 6 updates installed.'), [])
