#!/usr/bin/env python3
# tools/generate_enrollment.py
# Generates enrollment tokens for new operators.
#
# The server operator runs this tool to create a one-time token that
# a new team member uses to enroll their client with the server.
#
# Usage:
#   python tools/generate_enrollment.py
#   python tools/generate_enrollment.py --count 5
#   python tools/generate_enrollment.py --output tokens.txt
#
# The token is given to the operator out-of-band (in person, over a
# secure channel, etc.). Each token can only be used once.

import argparse
import os
import sys
import time

# Add the project source to the path so we can import talon modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from talon.server.auth import generate_enrollment_token


def main():
    # Set up command-line arguments
    parser = argparse.ArgumentParser(
        description="Generate enrollment tokens for new T.A.L.O.N. operators."
    )
    parser.add_argument(
        "--count", type=int, default=1,
        help="How many tokens to generate (default: 1)."
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Write tokens to a file instead of printing to the terminal."
    )
    args = parser.parse_args()

    # Generate the requested number of tokens
    tokens = []
    for _ in range(args.count):
        token = generate_enrollment_token()
        tokens.append(token)

    # Output the tokens
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    if args.output:
        # Write to file
        with open(args.output, "w") as f:
            f.write(f"# T.A.L.O.N. Enrollment Tokens\n")
            f.write(f"# Generated: {timestamp}\n")
            f.write(f"# Each token can only be used ONCE.\n")
            f.write(f"# Give these to operators through a secure channel.\n\n")
            for i, token in enumerate(tokens, 1):
                f.write(f"{i}. {token}\n")
        print(f"Wrote {args.count} token(s) to {args.output}")
    else:
        # Print to terminal
        print(f"\n  T.A.L.O.N. Enrollment Token(s)")
        print(f"  Generated: {timestamp}")
        print(f"  Each token can only be used ONCE.\n")
        for i, token in enumerate(tokens, 1):
            print(f"  {i}. {token}")
        print(f"\n  Give these to operators through a secure channel.\n")


if __name__ == "__main__":
    main()
