"""Split dataset CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

def _load_splitters():
    try:
        from obb_baseline.splitters import generate_split_bundle, scan_dota_export

        return generate_split_bundle, scan_dota_export
    except ModuleNotFoundError as exc:
        if exc.name and not exc.name.startswith("obb_baseline"):
            raise
        script_dir = Path(__file__).resolve().parent
        fallback_src = script_dir.parent / "src"
        if fallback_src.is_dir():
            sys.path.insert(0, str(fallback_src))
            from obb_baseline.splitters import generate_split_bundle, scan_dota_export

            return generate_split_bundle, scan_dota_export
        raise


generate_split_bundle, scan_dota_export = _load_splitters()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate benchmark split manifest from DOTA export"
    )
    parser.add_argument("--dota-root", required=True)
    parser.add_argument("--classes", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--holdout-seed", type=int, required=True)
    parser.add_argument("--split-seeds", required=True)
    parser.add_argument("--test-ratio", type=float, default=0.15)
    parser.add_argument("--val-ratio", type=float, default=0.15)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dota_root_input = Path(args.dota_root)
    dataset_name = dota_root_input.name
    dota_root = dota_root_input.resolve()
    out_dir = Path(args.out_dir).resolve()
    class_names = tuple(name.strip() for name in args.classes.split(",") if name.strip())
    split_seeds = [int(item.strip()) for item in args.split_seeds.split(",") if item.strip()]
    inventory = scan_dota_export(dota_root, class_names)
    bundle = generate_split_bundle(
        inventory,
        dataset_name=dataset_name,
        holdout_seed=args.holdout_seed,
        split_seeds=split_seeds,
        test_ratio=args.test_ratio,
        val_ratio=args.val_ratio,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "split_manifest.json").write_text(
        json.dumps(bundle.manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "split_summary.json").write_text(
        json.dumps(bundle.summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
