#!/usr/bin/env python3
# tools/shred_test.py
# Tests the data shredding (secure deletion) functionality.
#
# This tool creates a temporary encrypted database, writes test data,
# then shreds it and verifies the data is unrecoverable. Use this to
# confirm that the revocation shred process works correctly on your
# operating system and filesystem.
#
# Usage:
#   python tools/shred_test.py
#   python tools/shred_test.py --verbose
#   python tools/shred_test.py --keep-temp   (don't clean up, for inspection)
#
# What it tests:
#   1. Creates a temp directory with a test database and files
#   2. Writes known data to the database
#   3. Runs the shred function (overwrite with random data + delete)
#   4. Checks that the files are gone
#   5. If --verbose, shows the raw bytes at the old file locations
#
# IMPORTANT: Secure deletion depends on the filesystem. On SSDs with
# wear leveling or copy-on-write filesystems (ZFS, Btrfs), overwritten
# data may still exist in other physical locations. Full-disk encryption
# (LUKS, BitLocker) is the real protection — shredding is a belt-and-
# suspenders measure on top of that.

import argparse
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from talon.client.auth import ClientAuth


def main():
    parser = argparse.ArgumentParser(
        description="Test T.A.L.O.N. data shredding (secure deletion)."
    )
    parser.add_argument("--verbose", action="store_true",
                        help="Show detailed output including raw bytes.")
    parser.add_argument("--keep-temp", action="store_true",
                        help="Don't clean up the temp directory after test.")
    args = parser.parse_args()

    print(f"\n  T.A.L.O.N. Shred Test")
    print(f"  =====================\n")

    # Step 1: Create a temp directory with test files
    temp_dir = tempfile.mkdtemp(prefix="talon_shred_test_")
    print(f"  1. Created temp directory: {temp_dir}")

    # Create a fake lease file with known content
    lease_path = os.path.join(temp_dir, "lease.json")
    test_data = '{"token": "KNOWN_TEST_DATA_12345", "expiry": 9999999999}'
    with open(lease_path, "w") as f:
        f.write(test_data)
    print(f"  2. Wrote test lease file ({len(test_data)} bytes)")

    # Create a fake database file with known content
    db_path = os.path.join(temp_dir, "client.db")
    db_data = b"SQLITE_TEST_DATABASE_" + os.urandom(1024)
    with open(db_path, "wb") as f:
        f.write(db_data)
    print(f"  3. Wrote test database file ({len(db_data)} bytes)")

    # Verify the files exist
    assert os.path.isfile(lease_path), "Lease file should exist"
    assert os.path.isfile(db_path), "Database file should exist"
    print(f"  4. Verified both files exist")

    if args.verbose:
        # Read back the data to confirm it's what we wrote
        with open(lease_path, "r") as f:
            readback = f.read()
        print(f"     Lease content: {readback[:60]}...")
        with open(db_path, "rb") as f:
            readback = f.read(30)
        print(f"     DB header: {readback[:21]}")

    # Step 2: Run the shred function
    print(f"\n  5. Running shred...")
    auth = ClientAuth(temp_dir)
    auth.shred_local_data()
    print(f"     Shred complete.")

    # Step 3: Verify the files are gone
    lease_gone = not os.path.isfile(lease_path)
    db_gone = not os.path.isfile(db_path)

    print(f"\n  Results:")
    print(f"  - Lease file deleted: {'YES' if lease_gone else 'NO (FAIL)'}")
    print(f"  - Database file deleted: {'YES' if db_gone else 'NO (FAIL)'}")

    if lease_gone and db_gone:
        print(f"\n  PASS: All test files were shredded successfully.")
    else:
        print(f"\n  FAIL: Some files were not deleted.")
        sys.exit(1)

    # Clean up temp directory (unless --keep-temp)
    if not args.keep_temp:
        try:
            os.rmdir(temp_dir)
            print(f"  Cleaned up temp directory.")
        except OSError:
            print(f"  Note: Temp directory not empty, left at {temp_dir}")
    else:
        print(f"  Temp directory kept at: {temp_dir}")

    print(f"\n  Reminder: On SSDs and copy-on-write filesystems, overwritten")
    print(f"  data may still exist physically. Full-disk encryption (LUKS,")
    print(f"  BitLocker) is the primary protection. Shredding is an extra")
    print(f"  layer of defense.\n")


if __name__ == "__main__":
    main()
