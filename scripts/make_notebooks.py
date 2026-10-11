"""Genera los notebooks .ipynb (fuente única, reproducible). Ejecutar: python scripts/make_notebooks.py"""
from pathlib import Path

import nbformat as nbf

OUT = Path(__file__).resolve().parent.parent / "notebooks"
HEAD = "import sys; sys.path.insert(0, '.')\nfrom _common import *\n"


def nb(title, cells):
    n = nbf.v4.new_notebook()
    n.metadata["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
    n.cells = [nbf.v4.new_markdown_cell(f"# {title}\n\nEjecutar con **Kernel limpio → Run All**, en el orden documentado en `docs/NOTEBOOKS.md`.")]
    for kind, src in cells:
        n.cells.append(nbf.v4.new_markdown_cell(src) if kind == "md" else nbf.v4.new_code_cell(src))
    return n


NOTEBOOKS = {
"00a_instalar_modelos": ("00a · Instalar los modelos de IA (paso previo, una sola vez)", [
    ("md", "Instala las librerías de IA y descarga los modelos **desde Hugging Face** (necesita Internet y ~1.5 GB):\n\n- **Whisper small** (`Systran/faster-whisper-small`, conversión CTranslate2 del Whisper de OpenAI, licencia MIT): transcribe el audio.\n- **Qwen2.5-1.5B-Instruct q4_k_m** (`Qwen/Qwen2.5-1.5B-Instruct-GGUF`, de Alibaba, licencia Apache-2.0): decide si un fragmento es publicidad.\n\nSe guardan en la carpeta de datos de PodCleany (`models/`). Después, el sistema funciona sin descargar nada más de modelos."),
    ("code", HEAD + "import subprocess, sys\nreq = ROOT / 'requirements-ml.txt'\nsubprocess.run([sys.executable, '-m', 'pip', 'install', '--only-binary=:all:', '-r', str(req)], check=True)"),
    ("code", "subprocess.run([sys.executable, str(ROOT / 'scripts' / 'fetch_models.py')], check=True)"),
    ("code", "from podcleany.config import Config\nfrom podcleany.models import make_backends\nstt, clf, warns = make_backends(Config.load())\nprint('Transcriptor:', stt.name, '| Clasificador:', clf.name)\nprint('Avisos:', warns or 'ninguno: modelos listos')"),
]),
"00_setup_datos_demo": ("00 · Preparación y datos de demostración", [
    ("md", "Genera audio sintético reproducible (no es voz real) y un feed RSS local. Sirve a los demás notebooks."),
    ("code", HEAD + "W = workdir(); web = W / 'web'\nep1, m1, ep2, m2 = make_demo_site(web)\nprint(m1)\nprint(sorted(p.name for p in web.iterdir()))"),
]),
"01_normalizacion": ("01 · Normalización 16 kHz mono por bloques (E.6 paso 5)", [
    ("md", "ffmpeg decodifica por **pipes stdin/stdout**; los bloques de ~10 min se guardan como checkpoints y el episodio nunca se carga completo en RAM."),
    ("code", HEAD + "from podcleany import audio\nW = workdir(); src = W/'web'/'ep1.mp3'\ninfo = audio.normalize_to_blocks(src, W/'blocks', 16000, 60)\nprint(info, audio.count_blocks(W/'blocks'))\nx = audio.read_range(W/'blocks', 55, 65, 16000, 60)  # cruza dos bloques\nprint(x.shape, float(abs(x).max()))"),
]),
"02_fingerprints": ("02 · Fingerprints y coincidencias (E.6 paso 6)", [
    ("md", "Huellas por pares de picos espectrales. Se aprende el anuncio A en el episodio 1 y se reconoce en el 2 **sin transcribir**."),
    ("code", HEAD + "import numpy as np\nfrom podcleany import audio, fingerprint as fp\nW = workdir()\ndef load(src, name):\n    audio.normalize_to_blocks(src, W/name, 16000, 60)\n    return np.concatenate([audio.read_block(W/name, i) for i in range(audio.count_blocks(W/name))]).astype('float32')/32768\ne1, e2 = load(W/'web'/'ep1.mp3','b1'), load(W/'web'/'ep2.mp3','b2')\nad = e1[int(39.5*16000):int(59.5*16000)]\nh = fp.hashes_from_audio(ad); print('hashes del anuncio:', len(h))\nidx = fp.build_index([(1,'ad',20.0,fp.pack(h))])\nprint(fp.match(fp.hashes_from_audio(e2), idx))"),
]),
"03_senales": ("03 · Silencio, volumen y música (E.6 paso 6, en paralelo)", [
    ("code", HEAD + "from podcleany import audio, signals as sg\nW = workdir()\nx = audio.read_range(W/'blocks', 0, 134, 16000, 60)\nf = sg.frame_features(x)\nprint('silencios:', [(round(a,1), round(b,1)) for a,b in sg.silences(f['rms_db'])])\nprint('salto de volumen en 39.5 s:', round(sg.loudness_jump(f['rms_db'], 39.5),2))\nprint('música 40-59 s:', sg.music_score(f['flat'], f['cv'], 40, 59), ' habla 10-30 s:', sg.music_score(f['flat'], f['cv'], 10, 30))"),
]),
"04_transcripcion_llm": ("04 · Whisper (VAD) + clasificación LLM (E.6 paso 7)", [
    ("md", "Si hay modelos provisionados (`scripts/fetch_models.py`) se usan faster-whisper y llama.cpp; si no, este notebook usa los backends simulados de `tests/fakes.py` y lo indica."),
    ("code", HEAD + "import os, json\nfrom podcleany.config import Config\nfrom podcleany.models import make_backends\nfrom podcleany import audio, decision\nW = workdir(); cfg = Config.load(W/'data')\nstt, clf, warns = make_backends(cfg)\nprint(stt.name, clf.name, warns)\nif stt.name == 'none':\n    sys.path.insert(0, str(ROOT)); os.environ['PODCLEANY_FAKE_TRUTH'] = str(W/'truth.json')\n    (W/'truth.json').write_text(json.dumps([[0,8,'strong'],[39.5,59.5,'strong'],[92.5,107.5,'weak']]))\n    from tests.fakes import make_backends as fake; stt, clf, _ = fake(cfg); print('usando backends simulados')\nx = audio.read_range(W/'blocks', 0, 134, 16000, 60)\nutts = stt.transcribe(x, 0.0)\ncands = decision.llm_candidates(decision.group_utterances(utts), clf)\nprint([(c['start'], c['end'], max(c['ps'])) for c in cands])\njson.dump(cands, open(W/'cands.json','w'))"),
]),
"05_decision_y_corte": ("05 · Decisión con dos umbrales y corte con crossfade (E.6 paso 8)", [
    ("code", HEAD + "from podcleany import audio, decision, signals as sg\nfrom podcleany.config import Config\nimport json\nW = workdir(); cfg = Config.load(W/'data'); cands = json.load(open(W/'cands.json'))\nx = audio.read_range(W/'blocks', 0, 134, 16000, 60)\nfeats = sg.frame_features(x); sils = sg.silences(feats['rms_db'])\nfor c in cands:\n    seg = decision.combine(c, feats, sils, cfg)\n    print(seg and (round(seg['start_s'],1), round(seg['end_s'],1), round(seg['score'],2), decision.decide(seg['score'], cfg)))\nremovals = [(c['start'], c['end']) for c in cands]\ndur = audio.probe_duration(W/'web'/'ep1.mp3')\nout = audio.render_clean(W/'web'/'ep1.mp3', W/'limpio.mp3', dur, removals, cfg.crossfade_ms, cfg.min_keep_seconds)\nprint('duración original', round(dur,1), '-> final', round(out,1))"),
]),
"06_integracion": ("06 · Integración: API + worker independientes (E.6 pasos 1-11)", [
    ("md", "Arranca **API y worker como procesos separados**, y recorre el flujo solo por HTTP. El kernel no hace procesamiento pesado."),
    ("code", HEAD + "import requests, shutil\nW = workdir(); web = W/'web'; data = W/'int_data'\nshutil.rmtree(data, ignore_errors=True)\nsrv = serve(web, 8911); base = 'http://127.0.0.1:8911'\nwrite_feed(web, base, 1); write_feed(web, base, 2)\nCONFIG = {'backend_factory': 'tests.fakes:make_backends', 'block_seconds': 60, 'port': 8912}\ndata.mkdir(); (data/'config.json').write_text(json.dumps(CONFIG))\n(W/'truth.json').write_text(json.dumps([[0,8,'strong'],[39.5,59.5,'strong'],[92.5,107.5,'weak']]))\nenv = dict(os.environ, PODCLEANY_FAKE_TRUTH=str(W/'truth.json'), PYTHONPATH=str(ROOT))\nprocs = [subprocess.Popen([sys.executable, '-m', 'podcleany', k, '--data-dir', str(data)], env=env, cwd=ROOT) for k in ('api', 'worker')]\nAPI = 'http://127.0.0.1:8912'\nfor _ in range(50):\n    try:\n        requests.get(API + '/health', timeout=1); break\n    except Exception: time.sleep(0.3)\nprint(requests.get(API + '/health').json())"),
    ("code", "r = requests.post(API + '/episodes', json={'url': base + '/feed1.xml'}); print(r.status_code, r.json())\njid = r.json()['job_id']\nwith requests.get(f'{API}/jobs/{jid}/events', stream=True) as s:   # SSE\n    for line in s.iter_lines(decode_unicode=True):\n        if line.startswith('data:'): print(line[:120])\nep = requests.get(f\"{API}/episodes/{requests.get(f'{API}/jobs/{jid}').json()['episode_id']}\").json()\nfor s in ep['segments']: print(s['kind'], round(s['start'],1), round(s['end'],1), s['decision'])"),
    ("code", "# retroalimentación: conservar la intro, protegerla y confirmar los anuncios (aprende huellas)\nsegs = ep['segments']\nintro = min(segs, key=lambda s: s['start'])\nrequests.patch(f\"{API}/segments/{intro['id']}\", json={'decision': 'keep'})\nprint(requests.post(f\"{API}/episodes/{ep['id']}/protect\", json={'start': 0, 'end': 8, 'label': 'intro'}).json())\nfor s in segs:\n    if s is not intro: print(requests.patch(f\"{API}/segments/{s['id']}\", json={'decision': 'remove'}).json())\nprint(requests.post(f\"{API}/episodes/{ep['id']}/render\").json())\ntime.sleep(4)\nep = requests.get(f\"{API}/episodes/{ep['id']}\").json(); print(ep['clean'])\nr = requests.get(f\"{API}/episodes/{ep['id']}/audio/clean\", headers={'Range': 'bytes=0-99'}); print(r.status_code, r.headers['Content-Range'])"),
    ("code", "# episodio 2: el anuncio A se reconoce por huella (el guion simulado solo marca la intro como sospechosa)\n(W/'truth.json').write_text(json.dumps([[0,8,'strong']]))\nr = requests.post(API + '/episodes', json={'url': base + '/feed2.xml'}).json(); time.sleep(6)\nj = requests.get(f\"{API}/jobs/{r['job_id']}\").json(); ep2 = requests.get(f\"{API}/episodes/{j['episode_id']}\").json()\nprint([(s['source'], round(s['start'],1), round(s['end'],1)) for s in ep2['segments']])"),
    ("code", "for p in procs: p.terminate()\nsrv.shutdown()"),
]),
"07_interfaz_voila": ("07 · Interfaz Voilà + ipywidgets (adaptación propuesta de E.3)", [
    ("md", "Adaptación **propuesta**, no sustituye la API. Esta interfaz solo hace peticiones HTTP a la Local API (REST/JSON, SSE, Range 206); no escribe en SQLite ni invoca el worker. La interfaz principal entregada es la estática servida por la API (`/`). Ver `docs/ADAPTACION_VOILA.md`.\n\nEjecutar con `voila notebooks/07_interfaz_voila.ipynb` con la API en marcha (`python -m podcleany start`)."),
    ("code", "import requests, ipywidgets as w\nfrom IPython.display import display, Audio\nAPI = 'http://127.0.0.1:8765'\nurl = w.Text(placeholder='URL del episodio o RSS', layout=w.Layout(width='70%'))\nbtn = w.Button(description='Analizar episodio', button_style='primary')\nout = w.Output()\ndef go(_):\n    with out:\n        out.clear_output()\n        try:\n            r = requests.post(API + '/episodes', json={'url': url.value}); r.raise_for_status(); print('Enviado. Trabajo', r.json()['job_id'], '- siga el progreso en la API (/jobs/<id>/events).')\n        except Exception as e: print('No se pudo enviar:', e)\nbtn.on_click(go)\ndisplay(w.VBox([url, btn, out]))"),
]),
}

if __name__ == "__main__":
    for name, (title, cells) in NOTEBOOKS.items():
        nbf.write(nb(title, cells), OUT / f"{name}.ipynb")
        print("escrito", name)
