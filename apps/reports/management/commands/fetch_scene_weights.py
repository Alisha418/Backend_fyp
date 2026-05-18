"""
One-time setup: place ResNet18 ImageNet weights in model_ml/ for offline scene similarity.

  python manage.py fetch_scene_weights

Copies from PyTorch cache if already downloaded; otherwise downloads once (~45 MB).
"""
from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.reports.services.similarity_cleanup import scene_embedder_weights_path

PYTORCH_RESNET18_URL = 'https://download.pytorch.org/models/resnet18-f37072fd.pth'
CACHE_RELATIVE = Path('.cache') / 'torch' / 'hub' / 'checkpoints' / 'resnet18-f37072fd.pth'
# Official checkpoint size (bytes). Smaller file = incomplete/corrupt download.
EXPECTED_BYTES = 44_791_735
MIN_VALID_BYTES = 40_000_000


def _is_valid_weights(path: Path) -> bool:
    if not path.is_file():
        return False
    size = path.stat().st_size
    if size < MIN_VALID_BYTES:
        return False
    try:
        import torch

        torch.load(path, map_location='cpu', weights_only=True)
        return True
    except TypeError:
        try:
            import torch

            torch.load(path, map_location='cpu')
            return True
        except Exception:
            return False
    except Exception:
        return False


class Command(BaseCommand):
    help = 'Download or copy ResNet18 weights into model_ml/ (no runtime internet needed).'

    def _remove_dest(self, dest: Path) -> None:
        try:
            dest.unlink(missing_ok=True)
        except PermissionError:
            raise SystemExit(
                f'Cannot delete {dest} — stop Django runserver / close programs using it, '
                f'then run: python manage.py fetch_scene_weights --force',
            )

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Re-download even if a file already exists (fixes corrupt/partial .pth)',
        )

    def handle(self, *args, **options):
        dest = scene_embedder_weights_path()
        dest.parent.mkdir(parents=True, exist_ok=True)
        force = options['force']

        if dest.is_file() and not force:
            if _is_valid_weights(dest):
                self.stdout.write(self.style.SUCCESS(f'Already present: {dest}'))
                return
            self.stdout.write(
                self.style.WARNING(
                    f'Corrupt or incomplete file ({dest.stat().st_size} bytes, '
                    f'expected ~{EXPECTED_BYTES}). Re-downloading…',
                ),
            )
            self._remove_dest(dest)
        elif dest.is_file() and force:
            self._remove_dest(dest)
            self.stdout.write(self.style.WARNING('Removed old file; downloading fresh copy.'))

        cache = Path.home() / CACHE_RELATIVE
        if cache.is_file() and _is_valid_weights(cache):
            self.stdout.write(f'Copying from PyTorch cache: {cache}')
            shutil.copy2(cache, dest)
            self.stdout.write(self.style.SUCCESS(f'Saved to {dest}'))
            return

        self.stdout.write(f'Downloading {PYTORCH_RESNET18_URL} …')
        self.stdout.write(f'Target: {dest}')

        def _progress(block_num, block_size, total_size):
            if total_size <= 0:
                return
            pct = min(100, block_num * block_size * 100 / total_size)
            if block_num % 50 == 0:
                self.stdout.write(f'  {pct:.1f}%', ending='\r')

        urllib.request.urlretrieve(PYTORCH_RESNET18_URL, dest, reporthook=_progress)
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Done: {dest}'))
        self.stdout.write(
            'Restart Django. Worker resolve will load this file locally (no download per request).',
        )
