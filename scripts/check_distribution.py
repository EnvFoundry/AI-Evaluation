"""Check the wheel and source launcher from directories outside the checkout."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import venv
from zipfile import ZipFile

root = Path(__file__).resolve().parents[1]
version = tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']
wheels = sorted((root / 'dist').glob(f'envfoundry_ai_evaluation-{version}-*.whl'))
if len(wheels) != 1:
    raise SystemExit('build exactly one current wheel before checking the distribution')
with ZipFile(wheels[0]) as archive:
    for source in (root / 'src' / 'ai_eval').iterdir():
        if source.suffix not in ('.py', '.sql'):
            continue
        member = 'ai_eval/' + source.name
        if archive.read(member) != source.read_bytes():
            raise AssertionError(f'wheel contains stale source: {member}')

with tempfile.TemporaryDirectory(prefix='ai-eval-dist-') as directory:
    temporary = Path(directory)
    environment = temporary / 'venv'
    venv.EnvBuilder(with_pip=True, system_site_packages=True).create(environment)
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    subprocess.run([str(python), '-m', 'pip', 'install', '--no-deps', '--ignore-installed', str(wheels[0])],
                   cwd=temporary, check=True, stdout=subprocess.PIPE, text=True)
    clean_env = dict(os.environ)
    clean_env.pop('PYTHONPATH', None)
    code = 'import ai_eval; print(ai_eval.__file__)'
    installed = subprocess.check_output([str(python), '-c', code], cwd=temporary, env=clean_env, text=True).strip()
    if not Path(installed).resolve().is_relative_to(environment.resolve()):
        raise AssertionError(f'wheel check imported the wrong package: {installed}')
    capabilities = json.loads(subprocess.check_output([str(python), '-m', 'ai_eval', 'capabilities'],
                                                     cwd=temporary, env=clean_env, text=True))
    assert capabilities['version'] == version
    assert {'study', 'factorial', 'analyze-benchmark', 'analysis', 'guide', 'experiment'} <= set(capabilities['operations'])
    subprocess.run([str(python), '-c',
                    'from importlib.resources import files; assert files("ai_eval").joinpath("catalog.sql").read_text()'],
                   cwd=temporary, env=clean_env, check=True)
    plugin = temporary / 'relocated-plugin'
    plugin.mkdir()
    shutil.copytree(root / 'src', plugin / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.egg-info'))
    shutil.copy2(root / 'server.py', plugin / 'server.py')
    relocated = json.loads(subprocess.check_output([sys.executable, str(plugin / 'server.py'), 'capabilities'],
                                                   cwd=temporary, env=clean_env, text=True))
    assert relocated['scorers'] == capabilities['scorers']
    for name in ('plugin.json', '.claude-plugin/plugin.json', '.codex-plugin/plugin.json'):
        manifest = json.loads((root / name).read_text(encoding='utf-8'))
        assert manifest['name'] == 'ai-evaluation' and manifest['version'] == capabilities['version']
    print(json.dumps({'wheel': wheels[0].name, 'installed_import': 'passed', 'relocated_source': 'passed',
                      'plugin_metadata': 'passed'}))
