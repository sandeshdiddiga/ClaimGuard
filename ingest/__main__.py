"""Usage: python -m ingest [--raw-dir data/raw] [--out data/claimguard.db]

Reads the three CMS public-use ZIPs you downloaded into data/raw/ (HCPCS alpha-numeric file, Part B payment
limit files, NCCI MUE facility outpatient table) and builds the reference database. Only Level II codes
(first character a letter) are kept. The raw ZIPs are git-ignored and can be deleted afterwards.
"""

import argparse
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from ingest.build import build_reference_db

MAX_MEMBER_BYTES = 50 * 1024 * 1024  # the largest real file is about 3 MB

# key -> (text the zip file name must contain, test for the member that holds the data)
SOURCES = {
    "hcpcs": ("hcpc", lambda n: n.endswith(".txt") and "anweb" in n and "transaction" not in n),
    "drug_limits": ("payment_limit", lambda n: n.endswith(".csv") and "payment limit file" in n and "not payable" not in n),
    "mue": ("mue", lambda n: n.endswith(".csv")),
}


def find_inputs(raw_dir: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for key, (needle, _) in SOURCES.items():
        matches = sorted(p for p in raw_dir.glob("*.zip") if needle in p.name.lower())
        if len(matches) != 1:
            raise SystemExit(f"expected one zip matching '{needle}' in {raw_dir}, found {len(matches)}")
        found[key] = matches[0]
    return found


def extract_member(archive: Path, key: str, into: Path) -> Path:
    """Copy the one data file out of the zip. Only its base name is used, so no path inside the zip is trusted."""
    wanted = SOURCES[key][1]
    with zipfile.ZipFile(archive) as zf:
        names = [n for n in zf.namelist() if wanted(n.lower())]
        if len(names) != 1:
            raise SystemExit(f"expected one data file for {key} in {archive.name}, found {len(names)}")
        with zf.open(names[0]) as member:
            data = member.read(MAX_MEMBER_BYTES + 1)
    if len(data) > MAX_MEMBER_BYTES:
        raise SystemExit(f"{archive.name}: data file is too large")
    target = into / PurePosixPath(names[0]).name
    target.write_bytes(data)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ingest", description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, default=Path("data/claimguard.db"))
    args = parser.parse_args(argv)

    zips = find_inputs(args.raw_dir)
    with tempfile.TemporaryDirectory() as tmp:
        files = {key: extract_member(path, key, Path(tmp)) for key, path in zips.items()}
        meta = build_reference_db(
            args.out, hcpcs_file=files["hcpcs"], drug_limits_file=files["drug_limits"], mue_file=files["mue"]
        )
    print(f"built {args.out} ({args.out.stat().st_size / 1e6:.2f} MB)")
    for key, value in meta.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
